"""
Board Module
9x9 쿼리도 보드 표현
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


class Board:
    """9x9 쿼리도 보드"""

    SIZE = BOARD_SIZE
    WALL_POSITIONS = WALL_POSITIONS

    # 플레이어 시작 위치 (클래스 로드 후 설정)
    PLAYER1_START: Position = None  # type: ignore
    PLAYER2_START: Position = None  # type: ignore

    # 플레이어 목표 행
    PLAYER1_GOAL_ROW = 0  # 상단
    PLAYER2_GOAL_ROW = 8  # 하단

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


# 클래스 정의 후 시작 위치 설정
Board.PLAYER1_START = Position(8, 4)  # 하단 중앙
Board.PLAYER2_START = Position(0, 4)  # 상단 중앙
