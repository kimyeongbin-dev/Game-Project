"""
Player Module
좌석 상태 관리
"""

from dataclasses import dataclass
from typing import Optional

from .board import Goal, Position, reaches_any
from .layouts import SeatSlot


# 탈락 사유 (maze.md §9). 게임 종료 사유와 별개다
ELIMINATION_REASONS = ("surrender", "time_forfeit", "disconnect_forfeit")


@dataclass
class Player:
    """좌석 하나의 규칙 상태. 정체성(유저·닉네임)은 담지 않는다"""

    seat_no: int  # 1..N
    position: Position
    goals: tuple[Goal, ...]
    walls_remaining: int
    turns_taken: int = 0
    eliminated_order: Optional[int] = None    # 1 = 가장 먼저 탈락
    elimination_reason: Optional[str] = None

    def __post_init__(self):
        if self.seat_no < 1:
            raise ValueError("seat_no must be >= 1")
        if not self.goals:
            raise ValueError("goals must not be empty")
        self.goals = tuple(self.goals)

    @classmethod
    def from_slot(cls, seat_no: int, slot: SeatSlot, walls: int) -> "Player":
        """배치 테이블의 후보로 좌석 생성"""
        return cls(seat_no=seat_no, position=slot.start, goals=slot.goals, walls_remaining=walls)

    @property
    def is_eliminated(self) -> bool:
        return self.eliminated_order is not None

    def move_to(self, new_position: Position) -> None:
        """말을 새 위치로 이동"""
        self.position = new_position

    def use_wall(self) -> bool:
        """벽 사용 (남은 벽이 있으면 True 반환)"""
        if self.walls_remaining > 0:
            self.walls_remaining -= 1
            return True
        return False

    def has_walls(self) -> bool:
        """남은 벽이 있는지 확인"""
        return self.walls_remaining > 0

    def has_reached_goal(self) -> bool:
        """goals 중 하나라도 만족하면 도달"""
        return reaches_any(self.position, self.goals)

    def eliminate(self, order: int, reason: str) -> None:
        """탈락 표시. 순번은 GameState 가 매긴다"""
        if reason not in ELIMINATION_REASONS:
            raise ValueError(f"Invalid elimination reason: {reason}")
        self.eliminated_order = order
        self.elimination_reason = reason

    def copy(self) -> "Player":
        """좌석 상태 복사 (Position·Goal 은 불변이라 공유한다)"""
        return Player(
            seat_no=self.seat_no,
            position=self.position,
            goals=self.goals,
            walls_remaining=self.walls_remaining,
            turns_taken=self.turns_taken,
            eliminated_order=self.eliminated_order,
            elimination_reason=self.elimination_reason,
        )

    def to_dict(self) -> dict:
        return {
            "seat_no": self.seat_no,
            "position": self.position.to_dict(),
            "goals": [goal.to_dict() for goal in self.goals],
            "walls_remaining": self.walls_remaining,
            "turns_taken": self.turns_taken,
            "eliminated_order": self.eliminated_order,
            "elimination_reason": self.elimination_reason,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Player":
        return cls(
            seat_no=data["seat_no"],
            position=Position.from_dict(data["position"]),
            goals=tuple(Goal.from_dict(g) for g in data["goals"]),
            walls_remaining=data["walls_remaining"],
            turns_taken=data["turns_taken"],
            eliminated_order=data["eliminated_order"],
            elimination_reason=data["elimination_reason"],
        )
