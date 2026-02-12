"""
Room Manager Tests
친구대전 방 관리 테스트
"""

import pytest
from websocket.room_manager import RoomStatus


class TestRoomCreate:
    """방 생성 테스트"""

    def test_create_room(self, room_manager, mock_user):
        """방 생성 성공"""
        room = room_manager.create_room(
            mock_user.id, mock_user.nickname, mock_user.score
        )

        assert room is not None
        assert room.host.user_id == mock_user.id
        assert room.host.nickname == mock_user.nickname
        assert room.host.is_host is True
        assert room.status == RoomStatus.WAITING
        assert len(room.room_code) == 6

    def test_create_room_with_time_limit(self, room_manager, mock_user):
        """턴 시간 제한 설정하여 방 생성"""
        room = room_manager.create_room(
            mock_user.id, mock_user.nickname, mock_user.score,
            turn_time_limit=60
        )

        assert room.turn_time_limit == 60

    def test_create_room_already_in_room(self, room_manager, mock_user):
        """이미 방에 있는 경우 에러"""
        room_manager.create_room(mock_user.id, mock_user.nickname, mock_user.score)

        with pytest.raises(ValueError, match="이미 다른 방에 참가 중입니다"):
            room_manager.create_room(mock_user.id, mock_user.nickname, mock_user.score)


class TestRoomJoin:
    """방 참가 테스트"""

    def test_join_room(self, room_manager, mock_user, mock_user2):
        """방 참가 성공"""
        room = room_manager.create_room(
            mock_user.id, mock_user.nickname, mock_user.score
        )

        joined_room = room_manager.join_room(
            room.room_code, mock_user2.id, mock_user2.nickname, mock_user2.score
        )

        assert joined_room.guest is not None
        assert joined_room.guest.user_id == mock_user2.id
        assert joined_room.guest.is_host is False
        assert joined_room.status == RoomStatus.READY

    def test_join_room_invalid_code(self, room_manager, mock_user):
        """존재하지 않는 방 코드"""
        with pytest.raises(ValueError, match="존재하지 않는 방입니다"):
            room_manager.join_room("NOTEXIST", mock_user.id, mock_user.nickname)

    def test_join_room_full(self, room_manager, mock_user, mock_user2):
        """가득 찬 방 참가 시도 - 상태가 READY이므로 게임 시작 에러"""
        from tests.test_websocket.conftest import MockUser

        room = room_manager.create_room(
            mock_user.id, mock_user.nickname, mock_user.score
        )
        room_manager.join_room(
            room.room_code, mock_user2.id, mock_user2.nickname, mock_user2.score
        )

        user3 = MockUser(id=3, nickname="TestUser3", score=20.0)

        # 게스트 참가 시 READY 상태가 되므로 상태 검사가 먼저 발생
        with pytest.raises(ValueError, match="이미 게임이 시작된 방입니다"):
            room_manager.join_room(
                room.room_code, user3.id, user3.nickname, user3.score
            )

    def test_join_room_already_in_another(self, room_manager, mock_user, mock_user2):
        """이미 다른 방에 참가 중"""
        from tests.test_websocket.conftest import MockUser

        room1 = room_manager.create_room(
            mock_user.id, mock_user.nickname, mock_user.score
        )
        room2 = room_manager.create_room(
            mock_user2.id, mock_user2.nickname, mock_user2.score
        )

        user3 = MockUser(id=3, nickname="TestUser3", score=20.0)
        room_manager.join_room(room1.room_code, user3.id, user3.nickname)

        with pytest.raises(ValueError, match="이미 다른 방에 참가 중입니다"):
            room_manager.join_room(room2.room_code, user3.id, user3.nickname)

    def test_join_same_room_returns_room(self, room_manager, mock_user, mock_user2):
        """같은 방 재참가 시 방 반환"""
        room = room_manager.create_room(
            mock_user.id, mock_user.nickname, mock_user.score
        )
        room_manager.join_room(
            room.room_code, mock_user2.id, mock_user2.nickname
        )

        # 같은 방 다시 참가 시도
        result = room_manager.join_room(
            room.room_code, mock_user2.id, mock_user2.nickname
        )

        assert result.room_code == room.room_code


class TestRoomLeave:
    """방 나가기 테스트"""

    def test_leave_room_guest(self, room_manager, mock_user, mock_user2):
        """게스트 나가기"""
        room = room_manager.create_room(
            mock_user.id, mock_user.nickname, mock_user.score
        )
        room_manager.join_room(
            room.room_code, mock_user2.id, mock_user2.nickname
        )

        result = room_manager.leave_room(mock_user2.id)

        assert result is not None
        assert result.guest is None
        assert result.status == RoomStatus.WAITING

    def test_leave_room_host(self, room_manager, mock_user, mock_user2):
        """호스트 나가기 - 방 삭제"""
        room = room_manager.create_room(
            mock_user.id, mock_user.nickname, mock_user.score
        )
        room_code = room.room_code
        room_manager.join_room(room_code, mock_user2.id, mock_user2.nickname)

        result = room_manager.leave_room(mock_user.id)

        assert result is not None
        assert room_manager.get_room(room_code) is None
        assert room_manager.get_user_room(mock_user2.id) is None

    def test_leave_room_not_in_room(self, room_manager):
        """방에 없는 경우"""
        result = room_manager.leave_room(999)

        assert result is None


class TestRoomReady:
    """준비 상태 테스트"""

    def test_set_ready(self, room_manager, mock_user, mock_user2):
        """준비 상태 설정"""
        room = room_manager.create_room(
            mock_user.id, mock_user.nickname, mock_user.score
        )
        room_manager.join_room(
            room.room_code, mock_user2.id, mock_user2.nickname
        )

        room_manager.set_ready(mock_user.id, True)
        room_manager.set_ready(mock_user2.id, True)

        updated_room = room_manager.get_room(room.room_code)
        assert updated_room.host.is_ready is True
        assert updated_room.guest.is_ready is True
        assert updated_room.both_ready is True

    def test_set_ready_not_in_room(self, room_manager):
        """방에 없는 유저 준비 설정"""
        result = room_manager.set_ready(999, True)

        assert result is None

    def test_both_ready_with_one_ready(self, room_manager, mock_user, mock_user2):
        """한 명만 준비 시 both_ready False"""
        room = room_manager.create_room(
            mock_user.id, mock_user.nickname, mock_user.score
        )
        room_manager.join_room(
            room.room_code, mock_user2.id, mock_user2.nickname
        )

        room_manager.set_ready(mock_user.id, True)

        updated_room = room_manager.get_room(room.room_code)
        assert updated_room.both_ready is False


class TestRoomGame:
    """게임 시작/종료 테스트"""

    def test_start_game(self, room_manager, mock_user, mock_user2):
        """게임 시작"""
        room = room_manager.create_room(
            mock_user.id, mock_user.nickname, mock_user.score
        )
        room_manager.join_room(
            room.room_code, mock_user2.id, mock_user2.nickname
        )

        result = room_manager.start_game(room.room_code, "game-123")

        assert result.status == RoomStatus.PLAYING
        assert result.game_id == "game-123"

    def test_end_game(self, room_manager, mock_user, mock_user2):
        """게임 종료"""
        room = room_manager.create_room(
            mock_user.id, mock_user.nickname, mock_user.score
        )
        room_manager.join_room(
            room.room_code, mock_user2.id, mock_user2.nickname
        )
        room_manager.start_game(room.room_code, "game-123")

        result = room_manager.end_game(room.room_code)

        assert result.status == RoomStatus.FINISHED

    def test_start_game_invalid_room(self, room_manager):
        """존재하지 않는 방 게임 시작"""
        result = room_manager.start_game("NOTEXIST", "game-123")

        assert result is None


class TestRoomQuery:
    """방 조회 테스트"""

    def test_get_room(self, room_manager, mock_user):
        """방 조회"""
        room = room_manager.create_room(
            mock_user.id, mock_user.nickname, mock_user.score
        )

        found = room_manager.get_room(room.room_code)

        assert found is not None
        assert found.room_code == room.room_code

    def test_get_user_room(self, room_manager, mock_user):
        """유저가 속한 방 조회"""
        room = room_manager.create_room(
            mock_user.id, mock_user.nickname, mock_user.score
        )

        found = room_manager.get_user_room(mock_user.id)

        assert found is not None
        assert found.room_code == room.room_code

    def test_get_player_number(self, room_manager, mock_user, mock_user2):
        """플레이어 번호 조회"""
        room = room_manager.create_room(
            mock_user.id, mock_user.nickname, mock_user.score
        )
        room_manager.join_room(
            room.room_code, mock_user2.id, mock_user2.nickname
        )

        assert room.get_player_number(mock_user.id) == 1
        assert room.get_player_number(mock_user2.id) == 2
        assert room.get_player_number(999) == 0


class TestRoomStats:
    """방 통계 테스트"""

    def test_get_stats(self, room_manager, mock_user, mock_user2):
        """통계 조회"""
        room = room_manager.create_room(
            mock_user.id, mock_user.nickname, mock_user.score
        )
        room_manager.join_room(
            room.room_code, mock_user2.id, mock_user2.nickname
        )

        stats = room_manager.get_stats()

        assert stats["total_rooms"] == 1
        assert stats["ready_rooms"] == 1
        assert stats["waiting_rooms"] == 0


class TestRoomDelete:
    """방 삭제 테스트"""

    def test_delete_room(self, room_manager, mock_user, mock_user2):
        """방 삭제"""
        room = room_manager.create_room(
            mock_user.id, mock_user.nickname, mock_user.score
        )
        room_code = room.room_code
        room_manager.join_room(room_code, mock_user2.id, mock_user2.nickname)

        room_manager.delete_room(room_code)

        assert room_manager.get_room(room_code) is None
        assert room_manager.get_user_room(mock_user.id) is None
        assert room_manager.get_user_room(mock_user2.id) is None
