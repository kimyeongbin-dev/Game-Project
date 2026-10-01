"""
Board Tests
보드 및 위치 테스트
"""

import random

import pytest


from app.games.maze.core.board import Board, Goal, Position, BOARD_SIZE, WALL_POSITIONS, reaches_any
from app.games.maze.core.layouts import CORNER_SLOTS, LAYOUTS, Layout, get_layout


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


class TestGoal:
    """Goal (축 + 값) 테스트"""

    def test_row_goal(self):
        goal = Goal("row", 0)
        assert goal.is_reached(Position(0, 7)) is True
        assert goal.is_reached(Position(1, 0)) is False

    def test_col_goal(self):
        goal = Goal("col", 8)
        assert goal.is_reached(Position(3, 8)) is True
        assert goal.is_reached(Position(8, 3)) is False

    def test_reaches_any(self):
        goals = (Goal("row", 8), Goal("col", 8))
        assert reaches_any(Position(8, 0), goals) is True
        assert reaches_any(Position(0, 8), goals) is True
        assert reaches_any(Position(8, 8), goals) is True
        assert reaches_any(Position(4, 4), goals) is False

    @pytest.mark.parametrize("axis, value", [("diag", 0), ("row", 9), ("col", -1)])
    def test_invalid_goal(self, axis, value):
        with pytest.raises(ValueError):
            Goal(axis, value)

    def test_dict_roundtrip(self):
        goal = Goal("col", 3)
        assert Goal.from_dict(goal.to_dict()) == goal


class TestLayouts:
    """모드별 배치 테이블 (maze.md §11)"""

    def test_duel_matches_legacy_two_player_layout(self):
        """duel 은 구 2인 배치와 같다 — seat 1 이 하단 중앙에서 출발"""
        seat1, seat2 = LAYOUTS["duel"].assign()
        assert (seat1.start, seat1.goals) == (Position(8, 4), (Goal("row", 0),))
        assert (seat2.start, seat2.goals) == (Position(0, 4), (Goal("row", 8),))
        assert LAYOUTS["duel"].walls_per_seat == 10

    def test_trio_takes_three_distinct_corners(self):
        corners = {Position(0, 0), Position(0, 8), Position(8, 0), Position(8, 8)}
        for seed in range(20):
            slots = LAYOUTS["trio"].assign(random.Random(seed))
            starts = [s.start for s in slots]
            assert len(set(starts)) == 3
            assert set(starts) <= corners
        assert LAYOUTS["trio"].walls_per_seat == 7

    def test_corner_goals_are_opposite_edges(self):
        """꼭짓점의 목표는 대각 반대편 두 변"""
        for slot in CORNER_SLOTS:
            opposite = {Goal("row", 8 - slot.start.row), Goal("col", 8 - slot.start.col)}
            assert set(slot.goals) == opposite

    def test_quad_is_not_a_production_mode(self):
        """quad 는 인당 벽 수 미정 — 테이블에 없다"""
        with pytest.raises(ValueError):
            get_layout("quad")

    def test_layout_rejects_more_seats_than_slots(self):
        with pytest.raises(ValueError):
            Layout(slots=CORNER_SLOTS, seats=5, walls_per_seat=5, shuffle=True)
