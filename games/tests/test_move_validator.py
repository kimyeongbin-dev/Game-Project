"""
MoveValidator Tests
이동 및 벽 설치 유효성 검사 테스트
"""

import pytest
import sys
from pathlib import Path

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from games.game_Quoridor.core.move_validator import MoveValidator
from games.game_Quoridor.core.board import Position
from games.game_Quoridor.core.player import Player
from games.game_Quoridor.core.wall import Wall, WallManager, Orientation


class TestPawnMoveValidation:
    """폰 이동 유효성 테스트"""

    def setup_method(self):
        """각 테스트 전 설정"""
        self.player1 = Player.create_player1("P1")
        self.player2 = Player.create_player2("P2")
        self.wall_manager = WallManager()

    def test_valid_moves_from_start(self):
        """시작 위치에서 유효한 이동"""
        valid_moves = MoveValidator.get_valid_pawn_moves(
            self.player1, self.player2, self.wall_manager
        )

        # Player 1 (8, 4)에서 가능한 이동: 상, 좌, 우
        expected_positions = [
            Position(7, 4),  # 상
            Position(8, 3),  # 좌
            Position(8, 5),  # 우
        ]

        assert len(valid_moves) == 3
        for pos in expected_positions:
            assert pos in valid_moves

    def test_move_blocked_by_wall(self):
        """벽에 막힌 이동"""
        # Player 1 앞에 가로벽 설치
        self.wall_manager.add_wall(Wall(7, 3, Orientation.HORIZONTAL))
        self.wall_manager.add_wall(Wall(7, 4, Orientation.HORIZONTAL))

        valid_moves = MoveValidator.get_valid_pawn_moves(
            self.player1, self.player2, self.wall_manager
        )

        # 위로 이동 불가
        assert Position(7, 4) not in valid_moves

    def test_is_valid_pawn_move(self):
        """특정 이동 유효성 확인"""
        # 유효한 이동
        is_valid = MoveValidator.is_valid_pawn_move(
            self.player1, self.player2, Position(7, 4), self.wall_manager
        )
        assert is_valid is True

        # 무효한 이동 (너무 멈)
        is_valid = MoveValidator.is_valid_pawn_move(
            self.player1, self.player2, Position(6, 4), self.wall_manager
        )
        assert is_valid is False


class TestJumpMoves:
    """점프 이동 테스트"""

    def setup_method(self):
        self.wall_manager = WallManager()

    def test_jump_over_opponent(self):
        """상대방 넘어서 점프"""
        player1 = Player(1, "P1", Position(2, 4), 10)
        player2 = Player(2, "P2", Position(1, 4), 10)  # 바로 앞

        valid_moves = MoveValidator.get_valid_pawn_moves(
            player1, player2, self.wall_manager
        )

        # 상대 뒤로 점프 가능 (0, 4)
        assert Position(0, 4) in valid_moves

    def test_diagonal_jump_when_blocked(self):
        """직선 점프 불가 시 대각선 점프"""
        player1 = Player(1, "P1", Position(2, 4), 10)
        player2 = Player(2, "P2", Position(1, 4), 10)

        # 상대 뒤에 벽 설치 (직선 점프 막음)
        self.wall_manager.add_wall(Wall(0, 3, Orientation.HORIZONTAL))
        self.wall_manager.add_wall(Wall(0, 4, Orientation.HORIZONTAL))

        valid_moves = MoveValidator.get_valid_pawn_moves(
            player1, player2, self.wall_manager
        )

        # 직선 점프 불가, 대각선 점프 가능
        assert Position(0, 4) not in valid_moves
        # 대각선 (1, 3) 또는 (1, 5) 중 하나는 가능해야 함
        has_diagonal = Position(1, 3) in valid_moves or Position(1, 5) in valid_moves
        assert has_diagonal is True


class TestWallPlacementValidation:
    """벽 설치 유효성 테스트"""

    def setup_method(self):
        self.player1 = Player.create_player1("P1")
        self.player2 = Player.create_player2("P2")
        self.wall_manager = WallManager()

    def test_valid_wall_placement(self):
        """유효한 벽 설치"""
        wall = Wall(4, 4, Orientation.HORIZONTAL)

        is_valid = MoveValidator.is_valid_wall_placement(
            wall, self.player1, self.player2, self.wall_manager
        )

        assert is_valid is True

    def test_wall_overlap_invalid(self):
        """벽 겹침 불가"""
        # 첫 번째 벽 설치
        self.wall_manager.add_wall(Wall(4, 4, Orientation.HORIZONTAL))

        # 같은 위치에 다시 설치 시도
        wall = Wall(4, 4, Orientation.HORIZONTAL)

        is_valid = MoveValidator.is_valid_wall_placement(
            wall, self.player1, self.player2, self.wall_manager
        )

        assert is_valid is False

    def test_wall_cross_invalid(self):
        """벽 교차 불가"""
        # 가로벽 설치
        self.wall_manager.add_wall(Wall(4, 4, Orientation.HORIZONTAL))

        # 같은 중심점에 세로벽 설치 시도
        wall = Wall(4, 4, Orientation.VERTICAL)

        is_valid = MoveValidator.is_valid_wall_placement(
            wall, self.player1, self.player2, self.wall_manager
        )

        assert is_valid is False

    def test_no_walls_remaining(self):
        """벽 없으면 설치 불가"""
        self.player1._walls_remaining = 0

        wall = Wall(4, 4, Orientation.HORIZONTAL)

        is_valid = MoveValidator.is_valid_wall_placement(
            wall, self.player1, self.player2, self.wall_manager
        )

        assert is_valid is False

    def test_get_valid_wall_placements_count(self):
        """초기 상태 유효 벽 개수"""
        valid_walls = MoveValidator.get_valid_wall_placements(
            self.player1, self.player2, self.wall_manager
        )

        # 8x8 위치 x 2방향 = 128, 일부는 경로 차단으로 불가
        assert len(valid_walls) > 0
        assert len(valid_walls) <= 128
