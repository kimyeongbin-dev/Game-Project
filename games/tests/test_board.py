"""
Board Tests
보드 및 위치 테스트
"""

import pytest
import sys
from pathlib import Path

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from games.game_Quoridor.core.board import Board, Position, BOARD_SIZE, WALL_POSITIONS


class TestPosition:
    """Position 테스트"""

    def test_valid_position(self):
        """유효한 위치 생성"""
        pos = Position(4, 4)

        assert pos.row == 4
        assert pos.col == 4

    def test_corner_positions(self):
        """코너 위치"""
        corners = [
            Position(0, 0),
            Position(0, 8),
            Position(8, 0),
            Position(8, 8)
        ]

        for pos in corners:
            assert 0 <= pos.row < BOARD_SIZE
            assert 0 <= pos.col < BOARD_SIZE

    def test_invalid_position_negative(self):
        """음수 좌표 (무효)"""
        with pytest.raises(ValueError):
            Position(-1, 4)

        with pytest.raises(ValueError):
            Position(4, -1)

    def test_invalid_position_too_large(self):
        """범위 초과 좌표 (무효)"""
        with pytest.raises(ValueError):
            Position(9, 4)

        with pytest.raises(ValueError):
            Position(4, 9)

    def test_position_equality(self):
        """위치 동등성"""
        pos1 = Position(4, 4)
        pos2 = Position(4, 4)
        pos3 = Position(4, 5)

        assert pos1 == pos2
        assert pos1 != pos3

    def test_position_immutable(self):
        """위치 불변성"""
        pos = Position(4, 4)

        with pytest.raises(AttributeError):
            pos.row = 5

    def test_to_tuple(self):
        """튜플 변환"""
        pos = Position(3, 7)

        assert pos.to_tuple() == (3, 7)

    def test_from_tuple(self):
        """튜플에서 생성"""
        pos = Position.from_tuple((3, 7))

        assert pos.row == 3
        assert pos.col == 7


class TestBoardConstants:
    """보드 상수 테스트"""

    def test_board_size(self):
        """보드 크기"""
        assert Board.SIZE == 9
        assert BOARD_SIZE == 9

    def test_wall_positions(self):
        """벽 설치 위치 수"""
        assert Board.WALL_POSITIONS == 8
        assert WALL_POSITIONS == 8

    def test_player_start_positions(self):
        """플레이어 시작 위치"""
        assert Board.PLAYER1_START == Position(8, 4)
        assert Board.PLAYER2_START == Position(0, 4)

    def test_goal_rows(self):
        """골 라인"""
        assert Board.PLAYER1_GOAL_ROW == 0
        assert Board.PLAYER2_GOAL_ROW == 8

    def test_directions(self):
        """이동 방향"""
        assert len(Board.DIRECTIONS) == 4
        assert (-1, 0) in Board.DIRECTIONS  # 상
        assert (1, 0) in Board.DIRECTIONS   # 하
        assert (0, -1) in Board.DIRECTIONS  # 좌
        assert (0, 1) in Board.DIRECTIONS   # 우


class TestBoardValidation:
    """보드 유효성 검사 테스트"""

    def test_is_valid_cell_center(self):
        """중앙 셀 유효"""
        assert Board.is_valid_cell(4, 4) is True

    def test_is_valid_cell_corners(self):
        """코너 셀 유효"""
        assert Board.is_valid_cell(0, 0) is True
        assert Board.is_valid_cell(0, 8) is True
        assert Board.is_valid_cell(8, 0) is True
        assert Board.is_valid_cell(8, 8) is True

    def test_is_valid_cell_invalid(self):
        """범위 밖 셀 무효"""
        assert Board.is_valid_cell(-1, 4) is False
        assert Board.is_valid_cell(9, 4) is False
        assert Board.is_valid_cell(4, -1) is False
        assert Board.is_valid_cell(4, 9) is False

    def test_is_valid_wall_position(self):
        """유효한 벽 위치"""
        assert Board.is_valid_wall_position(0, 0) is True
        assert Board.is_valid_wall_position(7, 7) is True

    def test_is_valid_wall_position_invalid(self):
        """무효한 벽 위치"""
        assert Board.is_valid_wall_position(8, 0) is False
        assert Board.is_valid_wall_position(0, 8) is False


class TestBoardAdjacent:
    """인접 셀 테스트"""

    def test_adjacent_center(self):
        """중앙 셀 인접"""
        pos = Position(4, 4)
        adjacent = Board.get_adjacent_positions(pos)

        assert len(adjacent) == 4
        assert Position(3, 4) in adjacent  # 상
        assert Position(5, 4) in adjacent  # 하
        assert Position(4, 3) in adjacent  # 좌
        assert Position(4, 5) in adjacent  # 우

    def test_adjacent_corner(self):
        """코너 셀 인접"""
        pos = Position(0, 0)
        adjacent = Board.get_adjacent_positions(pos)

        assert len(adjacent) == 2
        assert Position(1, 0) in adjacent  # 하
        assert Position(0, 1) in adjacent  # 우

    def test_adjacent_edge(self):
        """가장자리 셀 인접"""
        pos = Position(0, 4)
        adjacent = Board.get_adjacent_positions(pos)

        assert len(adjacent) == 3


class TestBoardDirection:
    """방향 계산 테스트"""

    def test_direction_up(self):
        """상 방향"""
        direction = Board.get_direction(Position(5, 4), Position(4, 4))
        assert direction == (-1, 0)

    def test_direction_down(self):
        """하 방향"""
        direction = Board.get_direction(Position(4, 4), Position(5, 4))
        assert direction == (1, 0)

    def test_direction_left(self):
        """좌 방향"""
        direction = Board.get_direction(Position(4, 5), Position(4, 4))
        assert direction == (0, -1)

    def test_direction_right(self):
        """우 방향"""
        direction = Board.get_direction(Position(4, 4), Position(4, 5))
        assert direction == (0, 1)
