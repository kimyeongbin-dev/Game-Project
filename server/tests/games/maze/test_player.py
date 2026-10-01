"""
Player Tests
플레이어 상태 관리 테스트
"""

import pytest


from app.games.maze.core.player import Player
from app.games.maze.core.board import Position, Goal
from app.games.maze.core.layouts import LAYOUTS


def _seat1() -> Player:
    return Player.from_slot(1, LAYOUTS["duel"].slots[0], 10)


def _seat2() -> Player:
    return Player.from_slot(2, LAYOUTS["duel"].slots[1], 10)


class TestPlayerCreation:
    """플레이어 생성 테스트"""

    def test_create_seat1(self):
        """Seat 1 생성"""
        player = _seat1()

        assert player.seat_no == 1
        assert player.position == Position(8, 4)
        assert player.walls_remaining == 10
        assert player.goals == (Goal("row", 0),)

    def test_create_seat2(self):
        """Seat 2 생성"""
        player = _seat2()

        assert player.seat_no == 2
        assert player.position == Position(0, 4)
        assert player.walls_remaining == 10
        assert player.goals == (Goal("row", 8),)

    def test_create_with_custom_position(self):
        """커스텀 위치로 생성"""
        player = Player(
            seat_no=1,
            position=Position(4, 4),
            goals=(Goal("row", 0),),
            walls_remaining=5
        )

        assert player.position == Position(4, 4)
        assert player.walls_remaining == 5

    def test_invalid_seat_no(self):
        """잘못된 좌석 번호"""
        with pytest.raises(ValueError):
            Player(
                seat_no=0,
                position=Position(4, 4),
                goals=(Goal("row", 0),),
                walls_remaining=10
            )


class TestPlayerMovement:
    """플레이어 이동 테스트"""

    def test_move_to(self):
        """위치 이동"""
        player = _seat1()
        new_pos = Position(7, 4)

        player.move_to(new_pos)

        assert player.position == new_pos

    def test_move_multiple_times(self):
        """여러 번 이동"""
        player = _seat1()

        player.move_to(Position(7, 4))
        player.move_to(Position(6, 4))
        player.move_to(Position(5, 4))

        assert player.position == Position(5, 4)


class TestPlayerWalls:
    """플레이어 벽 관리 테스트"""

    def test_initial_walls(self):
        """초기 벽 개수"""
        player = _seat1()

        assert player.walls_remaining == 10
        assert player.has_walls() is True

    def test_use_wall(self):
        """벽 사용"""
        player = _seat1()

        result = player.use_wall()

        assert result is True
        assert player.walls_remaining == 9

    def test_use_all_walls(self):
        """모든 벽 사용"""
        player = _seat1()

        for _ in range(10):
            player.use_wall()

        assert player.walls_remaining == 0
        assert player.has_walls() is False

    def test_use_wall_when_empty(self):
        """벽 없을 때 사용 시도"""
        player = _seat1()
        player.walls_remaining = 0

        result = player.use_wall()

        assert result is False
        assert player.walls_remaining == 0


class TestPlayerGoal:
    """플레이어 골 확인 테스트"""

    def test_seat1_not_at_goal(self):
        """Seat 1 골 미도달"""
        player = _seat1()

        assert player.has_reached_goal() is False

    def test_seat1_at_goal(self):
        """Seat 1 골 도달"""
        player = _seat1()
        player.move_to(Position(0, 4))

        assert player.has_reached_goal() is True

    def test_seat2_not_at_goal(self):
        """Seat 2 골 미도달"""
        player = _seat2()

        assert player.has_reached_goal() is False

    def test_seat2_at_goal(self):
        """Seat 2 골 도달"""
        player = _seat2()
        player.move_to(Position(8, 4))

        assert player.has_reached_goal() is True


class TestPlayerCopy:
    """플레이어 복사 테스트"""

    def test_copy(self):
        """플레이어 복사"""
        original = _seat1()
        original.move_to(Position(5, 5))
        original.use_wall()

        copied = original.copy()

        assert copied.seat_no == original.seat_no
        assert copied.position == original.position
        assert copied.walls_remaining == original.walls_remaining

    def test_copy_independence(self):
        """복사본 독립성"""
        original = _seat1()
        copied = original.copy()

        # 복사본 수정
        copied.move_to(Position(5, 5))
        copied.use_wall()

        # 원본 변경 없음
        assert original.position == Position(8, 4)
        assert original.walls_remaining == 10


class TestPlayerGoalsAndElimination:
    """다중 골 / 탈락 테스트"""

    def test_corner_seat_multiple_goals(self):
        """코너 좌석: 행 또는 열 골 중 하나만 만족해도 도달"""
        player = Player(
            seat_no=1,
            position=Position(0, 0),
            goals=(Goal("row", 8), Goal("col", 8)),
            walls_remaining=7
        )

        player.move_to(Position(3, 8))
        assert player.has_reached_goal() is True

        player.move_to(Position(8, 2))
        assert player.has_reached_goal() is True

        player.move_to(Position(4, 4))
        assert player.has_reached_goal() is False

    def test_eliminate(self):
        """탈락 표시"""
        player = _seat1()
        assert player.is_eliminated is False

        player.eliminate(1, "surrender")

        assert player.is_eliminated is True
        assert player.eliminated_order == 1
        assert player.elimination_reason == "surrender"

    def test_eliminate_invalid_reason(self):
        """잘못된 탈락 사유"""
        player = _seat1()

        with pytest.raises(ValueError):
            player.eliminate(1, "bogus")

    def test_dict_roundtrip(self):
        """직렬화 왕복"""
        player = _seat1()
        player.turns_taken = 3
        player.eliminate(2, "time_forfeit")

        assert Player.from_dict(player.to_dict()) == player
