"""
Connection Manager Tests
WebSocket 연결 관리자 테스트
"""

import pytest


class TestConnectionConnect:
    """연결 테스트"""

    @pytest.mark.asyncio
    async def test_connect_new_user(self, connection_manager, mock_websocket, mock_user):
        """새 유저 연결"""
        conn = await connection_manager.connect(
            mock_websocket, mock_user.id, mock_user.nickname
        )

        assert conn is not None
        assert conn.user_id == mock_user.id
        assert conn.nickname == mock_user.nickname
        assert mock_websocket.accepted is True
        assert connection_manager.is_connected(mock_user.id) is True

    @pytest.mark.asyncio
    async def test_connect_replaces_existing(self, connection_manager, mock_user):
        """기존 연결 교체"""
        from tests.test_websocket.conftest import MockWebSocket

        ws1 = MockWebSocket()
        ws2 = MockWebSocket()

        # 첫 번째 연결
        await connection_manager.connect(ws1, mock_user.id, mock_user.nickname)
        assert connection_manager.is_connected(mock_user.id)

        # 두 번째 연결 (교체)
        await connection_manager.connect(ws2, mock_user.id, mock_user.nickname)

        # 첫 번째 연결은 닫혀야 함
        assert ws1.closed is True
        assert ws1.close_code == 4000

        # 두 번째 연결이 활성화
        conn = connection_manager.get_connection(mock_user.id)
        assert conn.websocket == ws2


class TestConnectionDisconnect:
    """연결 해제 테스트"""

    @pytest.mark.asyncio
    async def test_disconnect_user(self, connection_manager, mock_websocket, mock_user):
        """유저 연결 해제"""
        await connection_manager.connect(
            mock_websocket, mock_user.id, mock_user.nickname
        )

        await connection_manager.disconnect(mock_user.id)

        assert connection_manager.is_connected(mock_user.id) is False
        assert connection_manager.get_connection(mock_user.id) is None

    @pytest.mark.asyncio
    async def test_disconnect_nonexistent(self, connection_manager):
        """존재하지 않는 유저 연결 해제"""
        # 에러 없이 실행되어야 함
        await connection_manager.disconnect(999)


class TestConnectionMessage:
    """메시지 전송 테스트"""

    @pytest.mark.asyncio
    async def test_send_personal_message(self, connection_manager, mock_websocket, mock_user):
        """개인 메시지 전송"""
        await connection_manager.connect(
            mock_websocket, mock_user.id, mock_user.nickname
        )

        await connection_manager.send_personal(
            mock_user.id, {"type": "test", "data": "hello"}
        )

        assert len(mock_websocket.sent_messages) == 1
        assert mock_websocket.sent_messages[0]["type"] == "test"

    @pytest.mark.asyncio
    async def test_send_to_nonexistent_user(self, connection_manager):
        """존재하지 않는 유저에게 메시지 전송"""
        # 에러 없이 실행되어야 함
        await connection_manager.send_personal(999, {"type": "test"})


class TestGameManagement:
    """게임 관리 테스트"""

    @pytest.mark.asyncio
    async def test_join_and_leave_game(self, connection_manager, mock_websocket, mock_user):
        """게임 참가 및 탈퇴"""
        await connection_manager.connect(
            mock_websocket, mock_user.id, mock_user.nickname
        )

        # 게임 참가 (동기 메서드)
        connection_manager.join_game(mock_user.id, "game-123")
        conn = connection_manager.get_connection(mock_user.id)
        assert conn.current_game_id == "game-123"

        # 게임 탈퇴 (비동기 메서드)
        await connection_manager.leave_game(mock_user.id, "game-123")
        conn = connection_manager.get_connection(mock_user.id)
        assert conn.current_game_id is None

    @pytest.mark.asyncio
    async def test_send_to_game(self, connection_manager, mock_user, mock_user2):
        """게임 참가자들에게 메시지 전송"""
        from tests.test_websocket.conftest import MockWebSocket

        ws1 = MockWebSocket()
        ws2 = MockWebSocket()

        await connection_manager.connect(ws1, mock_user.id, mock_user.nickname)
        await connection_manager.connect(ws2, mock_user2.id, mock_user2.nickname)

        # 게임 참가 (동기 메서드)
        connection_manager.join_game(mock_user.id, "game-123")
        connection_manager.join_game(mock_user2.id, "game-123")

        await connection_manager.send_to_game(
            "game-123", {"type": "game_state", "data": {}}
        )

        assert len(ws1.sent_messages) == 1
        assert len(ws2.sent_messages) == 1


class TestRoomManagement:
    """방 관리 테스트"""

    @pytest.mark.asyncio
    async def test_join_and_leave_room(self, connection_manager, mock_websocket, mock_user):
        """방 참가 및 탈퇴"""
        await connection_manager.connect(
            mock_websocket, mock_user.id, mock_user.nickname
        )

        # 방 참가 (동기 메서드)
        connection_manager.join_room(mock_user.id, "ROOM01")
        conn = connection_manager.get_connection(mock_user.id)
        assert conn.current_room_code == "ROOM01"

        # 방 탈퇴 (비동기 메서드)
        await connection_manager.leave_room(mock_user.id, "ROOM01")
        conn = connection_manager.get_connection(mock_user.id)
        assert conn.current_room_code is None


class TestQueueState:
    """큐 상태 테스트"""

    @pytest.mark.asyncio
    async def test_set_queue_state(self, connection_manager, mock_websocket, mock_user):
        """큐 상태 설정"""
        await connection_manager.connect(
            mock_websocket, mock_user.id, mock_user.nickname
        )

        connection_manager.set_in_queue(mock_user.id, True)
        conn = connection_manager.get_connection(mock_user.id)
        assert conn.is_in_queue is True

        connection_manager.set_in_queue(mock_user.id, False)
        conn = connection_manager.get_connection(mock_user.id)
        assert conn.is_in_queue is False
