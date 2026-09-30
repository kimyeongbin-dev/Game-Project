"""
Wall Module
벽 표현 및 관리
"""

from dataclasses import dataclass
from enum import Enum
from typing import Set, Tuple

from .board import Board, Position


class Orientation(Enum):
    """벽 방향"""
    HORIZONTAL = "horizontal"
    VERTICAL = "vertical"


@dataclass(frozen=True)
class Wall:
    """벽 클래스 (불변)"""

    row: int
    col: int
    orientation: Orientation

    def __post_init__(self):
        if not Board.is_valid_wall_position(self.row, self.col):
            raise ValueError(f"Invalid wall position: ({self.row}, {self.col})")

    def get_blocked_edges(self) -> Set[Tuple[Tuple[int, int], Tuple[int, int]]]:
        """이 벽이 차단하는 셀 간 이동 경로 반환"""
        blocked = set()

        if self.orientation == Orientation.HORIZONTAL:
            # 수평 벽: 위아래 이동 차단
            # (row, col) <-> (row+1, col)
            # (row, col+1) <-> (row+1, col+1)
            blocked.add(((self.row, self.col), (self.row + 1, self.col)))
            blocked.add(((self.row + 1, self.col), (self.row, self.col)))
            blocked.add(((self.row, self.col + 1), (self.row + 1, self.col + 1)))
            blocked.add(((self.row + 1, self.col + 1), (self.row, self.col + 1)))
        else:
            # 수직 벽: 좌우 이동 차단
            # (row, col) <-> (row, col+1)
            # (row+1, col) <-> (row+1, col+1)
            blocked.add(((self.row, self.col), (self.row, self.col + 1)))
            blocked.add(((self.row, self.col + 1), (self.row, self.col)))
            blocked.add(((self.row + 1, self.col), (self.row + 1, self.col + 1)))
            blocked.add(((self.row + 1, self.col + 1), (self.row + 1, self.col)))

        return blocked

    def get_occupied_slots(self) -> Set[Tuple[int, int, str]]:
        """이 벽이 차지하는 슬롯 반환 (교차 검사용)"""
        slots = set()

        if self.orientation == Orientation.HORIZONTAL:
            # 수평 벽은 두 개의 수평 슬롯 차지
            slots.add((self.row, self.col, "h"))
            slots.add((self.row, self.col + 1, "h"))
            # 중앙 교차점 차지
            slots.add((self.row, self.col, "center"))
        else:
            # 수직 벽은 두 개의 수직 슬롯 차지
            slots.add((self.row, self.col, "v"))
            slots.add((self.row + 1, self.col, "v"))
            # 중앙 교차점 차지
            slots.add((self.row, self.col, "center"))

        return slots

    def intersects_with(self, other: "Wall") -> bool:
        """다른 벽과 교차하거나 겹치는지 확인"""
        my_slots = self.get_occupied_slots()
        other_slots = other.get_occupied_slots()
        return bool(my_slots & other_slots)

    def to_dict(self) -> dict:
        """딕셔너리로 변환"""
        return {
            "row": self.row,
            "col": self.col,
            "orientation": self.orientation.value
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Wall":
        """딕셔너리에서 생성"""
        return cls(
            row=data["row"],
            col=data["col"],
            orientation=Orientation(data["orientation"])
        )


class WallManager:
    """벽 관리 클래스"""

    def __init__(self):
        self._walls: list[Wall] = []
        self._blocked_edges: Set[Tuple[Tuple[int, int], Tuple[int, int]]] = set()
        self._occupied_slots: Set[Tuple[int, int, str]] = set()

    @property
    def walls(self) -> list[Wall]:
        return self._walls.copy()

    def add_wall(self, wall: Wall) -> bool:
        """벽 추가 (성공 시 True)"""
        if self.can_place_wall(wall):
            self._walls.append(wall)
            self._blocked_edges.update(wall.get_blocked_edges())
            self._occupied_slots.update(wall.get_occupied_slots())
            return True
        return False

    def can_place_wall(self, wall: Wall) -> bool:
        """벽을 설치할 수 있는지 확인 (다른 벽과 충돌 검사)"""
        return not bool(self._occupied_slots & wall.get_occupied_slots())

    def is_move_blocked(self, from_pos: Position, to_pos: Position) -> bool:
        """두 셀 간 이동이 벽에 의해 막혀있는지 확인"""
        edge = (from_pos.to_tuple(), to_pos.to_tuple())
        return edge in self._blocked_edges

    def remove_last_wall(self) -> Wall | None:
        """마지막 벽 제거 (되돌리기용)"""
        if self._walls:
            wall = self._walls.pop()
            self._blocked_edges -= wall.get_blocked_edges()
            self._occupied_slots -= wall.get_occupied_slots()
            return wall
        return None

    def copy(self) -> "WallManager":
        """깊은 복사"""
        new_manager = WallManager()
        for wall in self._walls:
            new_manager.add_wall(wall)
        return new_manager
