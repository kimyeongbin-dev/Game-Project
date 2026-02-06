"""
Player Tests
플레이어 상태 관리 테스트
"""

import pytest
import sys
from pathlib import Path

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from games.game_Quoridor.core.player import Player
from games.game_Quoridor.core.board import Position, Board


class TestPlayerCreation:
    """플레이어 생성 테스트"""

    def test_create_player1(self):
        """Player 1 생성"""
        player = Player.create_player1("Alice")

        assert player.player_id == 1
        assert player.name == "Alice"
        assert player.position == Board.PLAYER1_START
        assert player.walls_remaining == 10
        assert player.goal_row == 0

    def test_create_player2(self):
        """Player 2 생성"""
        player = Player.create_player2("Bob")

        assert player.player_id == 2
        assert player.name == "Bob"
        assert player.position == Board.PLAYER2_START
        assert player.walls_remaining == 10
        assert player.goal_row == 8

    def test_create_with_custom_position(self):
        """커스텀 위치로 생성"""
        player = Player(
            player_id=1,
            name="Test",
            position=Position(4, 4),
            walls_remaining=5
        )

        assert player.position == Position(4, 4)
        assert player.walls_remaining == 5

    def test_invalid_player_id(self):
        """잘못된 플레이어 ID"""
        with pytest.raises(ValueError):
            Player(
                player_id=3,
                name="Invalid",
                position=Position(4, 4)
            )


class TestPlayerMovement:
    """플레이어 이동 테스트"""

    def test_move_to(self):
        """위치 이동"""
        player = Player.create_player1("Test")
        new_pos = Position(7, 4)

        player.move_to(new_pos)

        assert player.position == new_pos

    def test_move_multiple_times(self):
        """여러 번 이동"""
        player = Player.create_player1("Test")

        player.move_to(Position(7, 4))
        player.move_to(Position(6, 4))
        player.move_to(Position(5, 4))

        assert player.position == Position(5, 4)


class TestPlayerWalls:
    """플레이어 벽 관리 테스트"""

    def test_initial_walls(self):
        """초기 벽 개수"""
        player = Player.create_player1("Test")

        assert player.walls_remaining == 10
        assert player.has_walls() is True

    def test_use_wall(self):
        """벽 사용"""
        player = Player.create_player1("Test")

        result = player.use_wall()

        assert result is True
        assert player.walls_remaining == 9

    def test_use_all_walls(self):
        """모든 벽 사용"""
        player = Player.create_player1("Test")

        for _ in range(10):
            player.use_wall()

        assert player.walls_remaining == 0
        assert player.has_walls() is False

    def test_use_wall_when_empty(self):
        """벽 없을 때 사용 시도"""
        player = Player.create_player1("Test")
        player._walls_remaining = 0

        result = player.use_wall()

        assert result is False
        assert player.walls_remaining == 0


class TestPlayerGoal:
    """플레이어 골 확인 테스트"""

    def test_player1_not_at_goal(self):
        """Player 1 골 미도달"""
        player = Player.create_player1("Test")

        assert player.has_reached_goal() is False

    def test_player1_at_goal(self):
        """Player 1 골 도달"""
        player = Player.create_player1("Test")
        player.move_to(Position(0, 4))

        assert player.has_reached_goal() is True

    def test_player2_not_at_goal(self):
        """Player 2 골 미도달"""
        player = Player.create_player2("Test")

        assert player.has_reached_goal() is False

    def test_player2_at_goal(self):
        """Player 2 골 도달"""
        player = Player.create_player2("Test")
        player.move_to(Position(8, 4))

        assert player.has_reached_goal() is True


class TestPlayerCopy:
    """플레이어 복사 테스트"""

    def test_copy(self):
        """플레이어 복사"""
        original = Player.create_player1("Original")
        original.move_to(Position(5, 5))
        original.use_wall()

        copied = original.copy()

        assert copied.player_id == original.player_id
        assert copied.name == original.name
        assert copied.position == original.position
        assert copied.walls_remaining == original.walls_remaining

    def test_copy_independence(self):
        """복사본 독립성"""
        original = Player.create_player1("Original")
        copied = original.copy()

        # 복사본 수정
        copied.move_to(Position(5, 5))
        copied.use_wall()

        # 원본 변경 없음
        assert original.position == Board.PLAYER1_START
        assert original.walls_remaining == 10
