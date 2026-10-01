"""
Layouts Module
모드별 배치 테이블 (maze.md §11)

인원·시작점·목표·인당 벽 수는 전부 이 테이블의 **값**이다. 새 모드는 행 추가로
끝나야 한다 — 그 외의 코드 변경이 필요하면 하드코딩이 남은 것이다
(docs/api/platform.md §5 확장성 원칙).
"""

import random
from dataclasses import dataclass
from typing import Optional

from .board import Goal, Position


@dataclass(frozen=True)
class SeatSlot:
    """좌석 후보 — 시작점과 그 시작점의 목표"""
    start: Position
    goals: tuple[Goal, ...]


@dataclass(frozen=True)
class Layout:
    """모드 하나의 배치 규칙"""
    slots: tuple[SeatSlot, ...]   # 후보 (seats 이상)
    seats: int                    # 정원
    walls_per_seat: int
    shuffle: bool                 # True 면 후보 중 seats 개를 랜덤 배정

    def __post_init__(self):
        if not (2 <= self.seats <= len(self.slots)):
            raise ValueError(f"seats({self.seats}) must be 2..len(slots)({len(self.slots)})")

    def assign(self, rng: Optional[random.Random] = None) -> list[SeatSlot]:
        """좌석 1..N 에 배정할 후보 목록 (인덱스 0 = seat_no 1)"""
        if self.shuffle:
            return (rng or random).sample(self.slots, self.seats)
        return list(self.slots[: self.seats])


def _row(value: int) -> Goal:
    return Goal("row", value)


def _col(value: int) -> Goal:
    return Goal("col", value)


# 네 꼭짓점 → 대각 반대편 두 변 (목표 17칸, 최단 거리 8 — 완전 대칭)
CORNER_SLOTS: tuple[SeatSlot, ...] = (
    SeatSlot(Position(0, 0), (_row(8), _col(8))),
    SeatSlot(Position(0, 8), (_row(8), _col(0))),
    SeatSlot(Position(8, 0), (_row(0), _col(8))),
    SeatSlot(Position(8, 8), (_row(0), _col(0))),
)

LAYOUTS: dict[str, Layout] = {
    # 변 중앙 대향 2점 → 반대 변. 순서 고정 (seat 1 이 하단에서 출발)
    "duel": Layout(
        slots=(
            SeatSlot(Position(8, 4), (_row(0),)),
            SeatSlot(Position(0, 4), (_row(8),)),
        ),
        seats=2,
        walls_per_seat=10,
        shuffle=False,
    ),
    # 네 꼭짓점 중 랜덤 3
    "trio": Layout(slots=CORNER_SLOTS, seats=3, walls_per_seat=7, shuffle=True),
    # "quad" (미래): 네 꼭짓점 전부 — 인당 벽 수 미정(§11)이라 아직 넣지 않는다
}


def get_layout(mode: str) -> Layout:
    """모드의 배치 규칙. 없는 모드면 ValueError"""
    try:
        return LAYOUTS[mode]
    except KeyError:
        raise ValueError(f"Unknown mode: {mode}") from None
