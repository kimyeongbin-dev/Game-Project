"""
MoveValidator Tests
이동 및 벽 설치 유효성 검사 테스트
"""

import pytest


from app.games.maze.core.layouts import LAYOUTS
from app.games.maze.core.move_validator import MoveValidator, Rejection
from app.games.maze.core.board import Position
from app.games.maze.core.player import Player
from app.games.maze.core.wall import Wall, WallManager, Orientation


class TestPawnMoveValidation:
    """폰 이동 유효성 테스트"""

    def setup_method(self):
        """각 테스트 전 설정"""
        self.player1 = Player.from_slot(1, LAYOUTS["duel"].slots[0], 10)
        self.player2 = Player.from_slot(2, LAYOUTS["duel"].slots[1], 10)
        self.wall_manager = WallManager()

    def test_valid_moves_from_start(self):
        """시작 위치에서 유효한 이동"""
        valid_moves = MoveValidator.get_valid_pawn_moves(
            self.player1, self.wall_manager
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
            self.player1, self.wall_manager
        )

        # 위로 이동 불가
        assert Position(7, 4) not in valid_moves

    def test_is_valid_pawn_move(self):
        """특정 이동 유효성 확인"""
        # 유효한 이동
        is_valid = MoveValidator.is_valid_pawn_move(
            self.player1, Position(7, 4), self.wall_manager
        )
        assert is_valid is True

        # 무효한 이동 (너무 멈)
        is_valid = MoveValidator.is_valid_pawn_move(
            self.player1, Position(6, 4), self.wall_manager
        )
        assert is_valid is False

    def test_can_move_onto_other_piece(self):
        """다른 말 위로 이동 가능 (점프 없음)"""
        self.player1.move_to(Position(5, 4))
        self.player2.move_to(Position(4, 4))

        valid_moves = MoveValidator.get_valid_pawn_moves(
            self.player1, self.wall_manager
        )

        assert Position(4, 4) in valid_moves
        assert Position(3, 4) not in valid_moves


class TestWallPlacementValidation:
    """벽 설치 유효성 테스트"""

    def setup_method(self):
        self.player1 = Player.from_slot(1, LAYOUTS["duel"].slots[0], 10)
        self.player2 = Player.from_slot(2, LAYOUTS["duel"].slots[1], 10)
        self.wall_manager = WallManager()

    def test_valid_wall_placement(self):
        """유효한 벽 설치"""
        wall = Wall(4, 4, Orientation.HORIZONTAL)

        is_valid = MoveValidator.is_valid_wall_placement(
            wall, self.player1, [self.player1, self.player2], self.wall_manager
        )

        assert is_valid is True

    def test_wall_overlap_invalid(self):
        """벽 겹침 불가"""
        # 첫 번째 벽 설치
        self.wall_manager.add_wall(Wall(4, 4, Orientation.HORIZONTAL))

        # 같은 위치에 다시 설치 시도
        wall = Wall(4, 4, Orientation.HORIZONTAL)

        is_valid = MoveValidator.is_valid_wall_placement(
            wall, self.player1, [self.player1, self.player2], self.wall_manager
        )

        assert is_valid is False

    def test_wall_cross_invalid(self):
        """벽 교차 불가"""
        # 가로벽 설치
        self.wall_manager.add_wall(Wall(4, 4, Orientation.HORIZONTAL))

        # 같은 중심점에 세로벽 설치 시도
        wall = Wall(4, 4, Orientation.VERTICAL)

        is_valid = MoveValidator.is_valid_wall_placement(
            wall, self.player1, [self.player1, self.player2], self.wall_manager
        )

        assert is_valid is False

    def test_no_walls_remaining(self):
        """벽 없으면 설치 불가"""
        self.player1.walls_remaining = 0

        wall = Wall(4, 4, Orientation.HORIZONTAL)

        is_valid = MoveValidator.is_valid_wall_placement(
            wall, self.player1, [self.player1, self.player2], self.wall_manager
        )

        assert is_valid is False

    def test_get_valid_wall_placements_count(self):
        """초기 상태 유효 벽 개수"""
        valid_walls = MoveValidator.get_valid_wall_placements(
            self.player1, [self.player1, self.player2], self.wall_manager
        )

        # 8x8 위치 x 2방향 = 128, 일부는 경로 차단으로 불가
        assert len(valid_walls) > 0
        assert len(valid_walls) <= 128

    def test_check_wall_placement_codes(self):
        """거절 사유 코드"""
        survivors = [self.player1, self.player2]
        wall = Wall(4, 4, Orientation.HORIZONTAL)
        assert MoveValidator.check_wall_placement(
            wall, self.player1, survivors, self.wall_manager
        ) is None

        self.wall_manager.add_wall(Wall(4, 4, Orientation.HORIZONTAL))
        assert MoveValidator.check_wall_placement(
            Wall(4, 4, Orientation.VERTICAL), self.player1, survivors, self.wall_manager
        ) == Rejection.INVALID_WALL_POSITION

        self.player1.walls_remaining = 0
        assert MoveValidator.check_wall_placement(
            wall, self.player1, survivors, WallManager()
        ) == Rejection.NO_WALLS_REMAINING

    def test_wall_blocks_path_code(self):
        """경로를 막는 벽은 생존 좌석 기준으로만 거절"""
        self.player2.position = Position(0, 0)
        # (0,0)-(0,1), (1,0)-(1,1) 차단 -> 출구는 (1,0)-(2,0) 하나
        assert self.wall_manager.add_wall(Wall(0, 0, Orientation.VERTICAL)) is True

        closer = Wall(1, 0, Orientation.HORIZONTAL)  # (1,0)-(2,0) 차단
        assert MoveValidator.check_wall_placement(
            closer, self.player1, [self.player1, self.player2], self.wall_manager
        ) == Rejection.WALL_BLOCKS_PATH
        assert MoveValidator.check_wall_placement(
            closer, self.player1, [self.player1], self.wall_manager
        ) is None
