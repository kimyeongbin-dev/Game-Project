"""
Player Module
플레이어 상태 관리
"""

from dataclasses import dataclass, field
from typing import Optional

from .board import Position, Board


@dataclass
class Player:
    """플레이어 클래스"""

    player_id: int  # 1 또는 2
    name: str
    position: Position
    walls_remaining: int = 10
    goal_row: int = field(init=False)

    INITIAL_WALLS = 10

    def __post_init__(self):
        if self.player_id not in (1, 2):
            raise ValueError("player_id must be 1 or 2")

        # 목표 행 설정
        self.goal_row = Board.PLAYER1_GOAL_ROW if self.player_id == 1 else Board.PLAYER2_GOAL_ROW

    def move_to(self, new_position: Position) -> None:
        """폰을 새 위치로 이동"""
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
        """목표에 도달했는지 확인"""
        return self.position.row == self.goal_row

    def copy(self) -> "Player":
        """플레이어 상태 복사"""
        return Player(
            player_id=self.player_id,
            name=self.name,
            position=Position(self.position.row, self.position.col),
            walls_remaining=self.walls_remaining
        )

    @classmethod
    def create_player1(cls, name: str = "Player") -> "Player":
        """Player 1 생성 (하단에서 시작)"""
        return cls(
            player_id=1,
            name=name,
            position=Board.PLAYER1_START
        )

    @classmethod
    def create_player2(cls, name: str = "AI") -> "Player":
        """Player 2 생성 (상단에서 시작)"""
        return cls(
            player_id=2,
            name=name,
            position=Board.PLAYER2_START
        )
