"""
WebSocket Handler Tests
WebSocket 메시지 핸들러 테스트
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from tests.test_websocket.conftest import MockWebSocket, MockUser


class MockGameState:
    """테스트용 Mock 게임 상태"""

    def __init__(self, game_id="test-game-123", current_turn=1, winner=None):
        self.game_id = game_id
        self.current_turn = current_turn
        self.winner = winner
        self.turn_count = 10
        self.status = MagicMock()
        self.status.value = "in_progress"
        self.game_mode = MagicMock()
        self.game_mode.value = "friend_match"

    def to_dict(self):
        return {
            "game_id": self.game_id,
            "current_turn": self.current_turn,
            "turn_count": self.turn_count,
            "winner": self.winner
        }


class TestHandleJoinQueue:
    """join_queue 핸들러 테스트"""

    @pytest.mark.asyncio
    async def test_join_queue_success(self, connection_manager, matchmaking_queue, mock_websocket, mock_user):
        """큐 참가 성공"""
        from routers.ws_game import handle_join_queue

        # 유저를 WebSocket에 연결
        await connection_manager.connect(mock_websocket, mock_user.id, mock_user.nickname)

        # SimpleUser 형식으로 변환
        user = MagicMock()
        user.id = mock_user.id
        user.nickname = mock_user.nickname
        user.score = mock_user.score

        # 핸들러 실행
        with patch("routers.ws_game.matchmaking_queue", matchmaking_queue), \
             patch("routers.ws_game.connection_manager", connection_manager), \
             patch("routers.ws_game.room_manager") as mock_room_manager:
            mock_room_manager.get_user_room.return_value = None
            await handle_join_queue(mock_websocket, user)

        # 응답 확인
        assert len(mock_websocket.sent_messages) >= 1
        assert mock_websocket.sent_messages[0]["type"] == "queue_joined"
        assert mock_websocket.sent_messages[0]["position"] == 1

    @pytest.mark.asyncio
    async def test_join_queue_already_in_queue(self, connection_manager, matchmaking_queue, mock_websocket, mock_user):
        """이미 큐에 있는 경우"""
        from routers.ws_game import handle_join_queue

        await connection_manager.connect(mock_websocket, mock_user.id, mock_user.nickname)
        matchmaking_queue.join(mock_user.id, mock_user.nickname, mock_user.score)

        user = MagicMock()
        user.id = mock_user.id
        user.nickname = mock_user.nickname
        user.score = mock_user.score

        with patch("routers.ws_game.matchmaking_queue", matchmaking_queue), \
             patch("routers.ws_game.connection_manager", connection_manager):
            await handle_join_queue(mock_websocket, user)

        # 에러 응답 확인
        assert any(msg.get("type") == "error" for msg in mock_websocket.sent_messages)


class TestHandleLeaveQueue:
    """leave_queue 핸들러 테스트"""

    @pytest.mark.asyncio
    async def test_leave_queue_success(self, connection_manager, matchmaking_queue, mock_websocket, mock_user):
        """큐 나가기 성공"""
        from routers.ws_game import handle_leave_queue

        await connection_manager.connect(mock_websocket, mock_user.id, mock_user.nickname)
        matchmaking_queue.join(mock_user.id, mock_user.nickname, mock_user.score)

        user = MagicMock()
        user.id = mock_user.id
        user.nickname = mock_user.nickname

        with patch("routers.ws_game.matchmaking_queue", matchmaking_queue), \
             patch("routers.ws_game.connection_manager", connection_manager):
            await handle_leave_queue(mock_websocket, user)

        assert any(msg.get("type") == "queue_left" for msg in mock_websocket.sent_messages)

    @pytest.mark.asyncio
    async def test_leave_queue_not_in_queue(self, connection_manager, matchmaking_queue, mock_websocket, mock_user):
        """큐에 없는 경우"""
        from routers.ws_game import handle_leave_queue

        user = MagicMock()
        user.id = mock_user.id
        user.nickname = mock_user.nickname

        with patch("routers.ws_game.matchmaking_queue", matchmaking_queue):
            await handle_leave_queue(mock_websocket, user)

        assert any(msg.get("type") == "error" for msg in mock_websocket.sent_messages)


class TestHandleCreateRoom:
    """create_room 핸들러 테스트"""

    @pytest.mark.asyncio
    async def test_create_room_success(self, connection_manager, room_manager, mock_websocket, mock_user):
        """방 생성 성공"""
        from routers.ws_game import handle_create_room

        await connection_manager.connect(mock_websocket, mock_user.id, mock_user.nickname)

        user = MagicMock()
        user.id = mock_user.id
        user.nickname = mock_user.nickname
        user.score = mock_user.score

        with patch("routers.ws_game.matchmaking_queue") as mock_mq, \
             patch("routers.ws_game.connection_manager", connection_manager), \
             patch("routers.ws_game.room_manager", room_manager):
            mock_mq.is_in_queue.return_value = False
            await handle_create_room(mock_websocket, user, turn_time_limit=30)

        assert any(msg.get("type") == "room_created" for msg in mock_websocket.sent_messages)

    @pytest.mark.asyncio
    async def test_create_room_while_in_queue(self, connection_manager, room_manager, mock_websocket, mock_user):
        """큐에 있는 상태에서 방 생성 시도"""
        from routers.ws_game import handle_create_room

        user = MagicMock()
        user.id = mock_user.id
        user.nickname = mock_user.nickname
        user.score = mock_user.score

        with patch("routers.ws_game.matchmaking_queue") as mock_mq:
            mock_mq.is_in_queue.return_value = True
            await handle_create_room(mock_websocket, user, turn_time_limit=30)

        assert any(msg.get("code") == "in_queue" for msg in mock_websocket.sent_messages)


class TestHandleJoinRoom:
    """join_room 핸들러 테스트"""

    @pytest.mark.asyncio
    async def test_join_room_success(self, connection_manager, room_manager, mock_websocket, mock_user, mock_user2):
        """방 참가 성공"""
        from routers.ws_game import handle_join_room

        # 호스트 연결 및 방 생성
        ws_host = MockWebSocket()
        await connection_manager.connect(ws_host, mock_user.id, mock_user.nickname)
        room = room_manager.create_room(mock_user.id, mock_user.nickname, mock_user.score)
        connection_manager.join_room(mock_user.id, room.room_code)

        # 게스트 연결
        await connection_manager.connect(mock_websocket, mock_user2.id, mock_user2.nickname)

        user = MagicMock()
        user.id = mock_user2.id
        user.nickname = mock_user2.nickname
        user.score = mock_user2.score

        with patch("routers.ws_game.matchmaking_queue") as mock_mq, \
             patch("routers.ws_game.connection_manager", connection_manager), \
             patch("routers.ws_game.room_manager", room_manager):
            mock_mq.is_in_queue.return_value = False
            await handle_join_room(mock_websocket, user, room.room_code)

        assert any(msg.get("type") == "room_joined" for msg in mock_websocket.sent_messages)

    @pytest.mark.asyncio
    async def test_join_room_invalid_code(self, connection_manager, room_manager, mock_websocket, mock_user):
        """잘못된 방 코드"""
        from routers.ws_game import handle_join_room

        user = MagicMock()
        user.id = mock_user.id
        user.nickname = mock_user.nickname
        user.score = mock_user.score

        with patch("routers.ws_game.matchmaking_queue") as mock_mq, \
             patch("routers.ws_game.room_manager", room_manager):
            mock_mq.is_in_queue.return_value = False
            await handle_join_room(mock_websocket, user, "NOTEXIST")

        assert any(msg.get("type") == "error" for msg in mock_websocket.sent_messages)


class TestHandleReady:
    """ready 핸들러 테스트"""

    @pytest.mark.asyncio
    async def test_ready_not_in_room(self, mock_websocket, mock_user):
        """방에 없는 상태에서 준비"""
        from routers.ws_game import handle_ready

        user = MagicMock()
        user.id = mock_user.id
        user.nickname = mock_user.nickname

        with patch("routers.ws_game.room_manager") as mock_rm:
            mock_rm.get_user_room.return_value = None
            await handle_ready(mock_websocket, user)

        assert any(msg.get("code") == "not_in_room" for msg in mock_websocket.sent_messages)


class TestHandleMove:
    """move 핸들러 테스트"""

    @pytest.mark.asyncio
    async def test_move_not_in_game(self, connection_manager, mock_websocket, mock_user):
        """게임 중이 아닌 상태에서 이동"""
        from routers.ws_game import handle_move

        await connection_manager.connect(mock_websocket, mock_user.id, mock_user.nickname)

        user = MagicMock()
        user.id = mock_user.id
        user.nickname = mock_user.nickname

        with patch("routers.ws_game.connection_manager", connection_manager):
            await handle_move(mock_websocket, user, row=5, col=4)

        assert any(msg.get("code") == "not_in_game" for msg in mock_websocket.sent_messages)

    @pytest.mark.asyncio
    async def test_move_success(self, connection_manager, mock_websocket, mock_user, mock_user2):
        """이동 성공"""
        from routers.ws_game import handle_move

        ws1 = mock_websocket
        ws2 = MockWebSocket()

        await connection_manager.connect(ws1, mock_user.id, mock_user.nickname)
        await connection_manager.connect(ws2, mock_user2.id, mock_user2.nickname)

        game_id = "test-game-123"
        connection_manager.join_game(mock_user.id, game_id)
        connection_manager.join_game(mock_user2.id, game_id)

        user = MagicMock()
        user.id = mock_user.id
        user.nickname = mock_user.nickname

        mock_game = MockGameState(game_id=game_id, current_turn=1)

        with patch("routers.ws_game.connection_manager", connection_manager), \
             patch("routers.ws_game.quoridor_service") as mock_qs:
            mock_qs.get_game = AsyncMock(return_value=mock_game)
            mock_qs.move_pawn = AsyncMock(return_value=(True, "이동 성공", mock_game))

            await handle_move(ws1, user, row=7, col=4)

        # 성공 시 game_state 메시지가 전송됨
        assert any(msg.get("type") == "game_state" for msg in ws1.sent_messages)

    @pytest.mark.asyncio
    async def test_move_not_your_turn(self, connection_manager, mock_websocket, mock_user, mock_user2):
        """상대방 턴에 이동 시도"""
        from routers.ws_game import handle_move

        ws1 = mock_websocket
        ws2 = MockWebSocket()

        await connection_manager.connect(ws1, mock_user.id, mock_user.nickname)
        await connection_manager.connect(ws2, mock_user2.id, mock_user2.nickname)

        game_id = "test-game-123"
        connection_manager.join_game(mock_user.id, game_id)
        connection_manager.join_game(mock_user2.id, game_id)

        # player2 (mock_user2) 턴
        user = MagicMock()
        user.id = mock_user2.id
        user.nickname = mock_user2.nickname

        mock_game = MockGameState(game_id=game_id, current_turn=1)  # player1 턴

        with patch("routers.ws_game.connection_manager", connection_manager), \
             patch("routers.ws_game.quoridor_service") as mock_qs:
            mock_qs.get_game = AsyncMock(return_value=mock_game)

            await handle_move(ws2, user, row=1, col=4)

        assert any(msg.get("code") == "not_your_turn" for msg in ws2.sent_messages)


class TestHandleWall:
    """wall 핸들러 테스트"""

    @pytest.mark.asyncio
    async def test_wall_not_in_game(self, connection_manager, mock_websocket, mock_user):
        """게임 중이 아닌 상태에서 벽 설치"""
        from routers.ws_game import handle_wall

        await connection_manager.connect(mock_websocket, mock_user.id, mock_user.nickname)

        user = MagicMock()
        user.id = mock_user.id
        user.nickname = mock_user.nickname

        with patch("routers.ws_game.connection_manager", connection_manager):
            await handle_wall(mock_websocket, user, row=4, col=4, orientation="H")

        assert any(msg.get("code") == "not_in_game" for msg in mock_websocket.sent_messages)

    @pytest.mark.asyncio
    async def test_wall_success(self, connection_manager, mock_websocket, mock_user, mock_user2):
        """벽 설치 성공"""
        from routers.ws_game import handle_wall

        ws1 = mock_websocket
        ws2 = MockWebSocket()

        await connection_manager.connect(ws1, mock_user.id, mock_user.nickname)
        await connection_manager.connect(ws2, mock_user2.id, mock_user2.nickname)

        game_id = "test-game-123"
        connection_manager.join_game(mock_user.id, game_id)
        connection_manager.join_game(mock_user2.id, game_id)

        user = MagicMock()
        user.id = mock_user.id
        user.nickname = mock_user.nickname

        mock_game = MockGameState(game_id=game_id, current_turn=1)

        with patch("routers.ws_game.connection_manager", connection_manager), \
             patch("routers.ws_game.quoridor_service") as mock_qs:
            mock_qs.get_game = AsyncMock(return_value=mock_game)
            mock_qs.place_wall = AsyncMock(return_value=(True, "벽 설치 성공", mock_game))

            await handle_wall(ws1, user, row=4, col=4, orientation="H")

        assert any(msg.get("type") == "game_state" for msg in ws1.sent_messages)


class TestHandleSurrender:
    """surrender 핸들러 테스트"""

    @pytest.mark.asyncio
    async def test_surrender_not_in_game(self, connection_manager, mock_websocket, mock_user):
        """게임 중이 아닌 상태에서 항복"""
        from routers.ws_game import handle_surrender

        await connection_manager.connect(mock_websocket, mock_user.id, mock_user.nickname)

        user = MagicMock()
        user.id = mock_user.id
        user.nickname = mock_user.nickname

        with patch("routers.ws_game.connection_manager", connection_manager):
            await handle_surrender(mock_websocket, user)

        assert any(msg.get("code") == "not_in_game" for msg in mock_websocket.sent_messages)


class TestHandleMessage:
    """handle_message 라우팅 테스트"""

    @pytest.mark.asyncio
    async def test_unknown_message_type(self, mock_websocket, mock_user):
        """알 수 없는 메시지 타입"""
        from routers.ws_game import handle_message

        user = MagicMock()
        user.id = mock_user.id
        user.nickname = mock_user.nickname

        await handle_message(mock_websocket, user, {"type": "unknown_type"})

        assert any(msg.get("code") == "unknown_type" for msg in mock_websocket.sent_messages)

    @pytest.mark.asyncio
    async def test_move_missing_params(self, mock_websocket, mock_user):
        """move 메시지에 필수 파라미터 누락"""
        from routers.ws_game import handle_message

        user = MagicMock()
        user.id = mock_user.id

        await handle_message(mock_websocket, user, {"type": "move", "row": 5})  # col 누락

        assert any(msg.get("type") == "error" for msg in mock_websocket.sent_messages)

    @pytest.mark.asyncio
    async def test_wall_missing_params(self, mock_websocket, mock_user):
        """wall 메시지에 필수 파라미터 누락"""
        from routers.ws_game import handle_message

        user = MagicMock()
        user.id = mock_user.id

        await handle_message(mock_websocket, user, {"type": "wall", "row": 4, "col": 4})  # orientation 누락

        assert any(msg.get("type") == "error" for msg in mock_websocket.sent_messages)

    @pytest.mark.asyncio
    async def test_join_room_missing_code(self, mock_websocket, mock_user):
        """join_room 메시지에 room_code 누락"""
        from routers.ws_game import handle_message

        user = MagicMock()
        user.id = mock_user.id

        await handle_message(mock_websocket, user, {"type": "join_room"})  # room_code 누락

        assert any(msg.get("type") == "error" for msg in mock_websocket.sent_messages)
