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
        from tests.ws.conftest import MockWebSocket

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


class TestReplacedConnection:
    """교체된 옛 연결의 정리가 새 연결을 지우지 않는다"""

    @pytest.mark.asyncio
    async def test_stale_disconnect_keeps_new_connection(self, connection_manager, mock_user):
        from tests.ws.conftest import MockWebSocket

        old, new = MockWebSocket(), MockWebSocket()
        await connection_manager.connect(old, mock_user.id, mock_user.nickname)
        await connection_manager.connect(new, mock_user.id, mock_user.nickname)

        # 옛 핸들러가 끝나며 자기 소켓으로 disconnect 를 부른다
        await connection_manager.disconnect(mock_user.id, old)

        assert connection_manager.get_connection(mock_user.id).websocket is new

    @pytest.mark.asyncio
    async def test_own_disconnect_removes(self, connection_manager, mock_websocket, mock_user):
        await connection_manager.connect(mock_websocket, mock_user.id, mock_user.nickname)
        await connection_manager.disconnect(mock_user.id, mock_websocket)
        assert not connection_manager.is_connected(mock_user.id)


class TestLocalUsers:
    """연결 맵만 로컬이다 — 게임·방 소속은 Redis 권위"""

    @pytest.mark.asyncio
    async def test_local_user_ids(self, connection_manager, mock_user, mock_user2):
        from tests.ws.conftest import MockWebSocket

        assert connection_manager.local_user_ids() == set()
        await connection_manager.connect(MockWebSocket(), mock_user.id, mock_user.nickname)
        await connection_manager.connect(MockWebSocket(), mock_user2.id, mock_user2.nickname)
        assert connection_manager.local_user_ids() == {mock_user.id, mock_user2.id}

        await connection_manager.disconnect(mock_user.id)
        assert connection_manager.local_user_ids() == {mock_user2.id}
        assert connection_manager.get_stats() == {"total_connections": 1}

    def test_no_membership_state(self, connection_manager):
        for attr in ("_game_players", "_room_players", "join_game", "join_room", "send_to_game"):
            assert not hasattr(connection_manager, attr)
