"""
Board Module
9x9 보드 기하 — 좌표, 인접, 목표 판정
"""

from dataclasses import dataclass
from typing import Tuple

# 보드 크기 상수 (순환 의존성 방지)
BOARD_SIZE = 9
WALL_POSITIONS = 8


@dataclass(frozen=True)
class Position:
    """보드 위치를 나타내는 불변 클래스"""
    row: int
    col: int

    def __post_init__(self):
        if not (0 <= self.row < BOARD_SIZE and 0 <= self.col < BOARD_SIZE):
            raise ValueError(f"Invalid position: ({self.row}, {self.col})")

    def to_tuple(self) -> Tuple[int, int]:
        return (self.row, self.col)

    @classmethod
    def from_tuple(cls, t: Tuple[int, int]) -> "Position":
        return cls(t[0], t[1])

    def to_dict(self) -> dict:
        return {"row": self.row, "col": self.col}

    @classmethod
    def from_dict(cls, data: dict) -> "Position":
        return cls(data["row"], data["col"])


@dataclass(frozen=True)
class Goal:
    """목표 한 줄 — 축(row|col) + 값. 좌석의 목표는 이것의 목록이다 (maze.md §11)"""
    axis: str
    value: int

    AXES = ("row", "col")

    def __post_init__(self):
        if self.axis not in self.AXES:
            raise ValueError(f"Invalid goal axis: {self.axis}")
        if not (0 <= self.value < BOARD_SIZE):
            raise ValueError(f"Invalid goal value: {self.value}")

    def is_reached(self, pos: Position) -> bool:
        return (pos.row if self.axis == "row" else pos.col) == self.value

    def to_dict(self) -> dict:
        return {"axis": self.axis, "value": self.value}

    @classmethod
    def from_dict(cls, data: dict) -> "Goal":
        return cls(data["axis"], data["value"])


def reaches_any(pos: Position, goals) -> bool:
    """goals 중 하나라도 만족하면 도달 (maze.md §5 승리 판정)"""
    return any(goal.is_reached(pos) for goal in goals)


class Board:
    """9x9 보드"""

    SIZE = BOARD_SIZE
    WALL_POSITIONS = WALL_POSITIONS

    # 이동 방향 (상, 하, 좌, 우)
    DIRECTIONS = [(-1, 0), (1, 0), (0, -1), (0, 1)]

    @classmethod
    def is_valid_cell(cls, row: int, col: int) -> bool:
        """셀 좌표가 유효한지 확인"""
        return 0 <= row < cls.SIZE and 0 <= col < cls.SIZE

    @classmethod
    def is_valid_wall_position(cls, row: int, col: int) -> bool:
        """벽 설치 위치가 유효한지 확인"""
        return 0 <= row < cls.WALL_POSITIONS and 0 <= col < cls.WALL_POSITIONS

    @classmethod
    def get_adjacent_positions(cls, pos: Position) -> list[Position]:
        """인접한 셀 위치 반환 (벽 무시)"""
        adjacent = []
        for dr, dc in cls.DIRECTIONS:
            new_row, new_col = pos.row + dr, pos.col + dc
            if cls.is_valid_cell(new_row, new_col):
                adjacent.append(Position(new_row, new_col))
        return adjacent

    @classmethod
    def get_direction(cls, from_pos: Position, to_pos: Position) -> Tuple[int, int]:
        """두 위치 사이의 방향 벡터 반환"""
        return (to_pos.row - from_pos.row, to_pos.col - from_pos.col)
