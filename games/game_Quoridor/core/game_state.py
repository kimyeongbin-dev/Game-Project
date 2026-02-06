"""
Game State Module
게임 상태 관리 (핵심 모듈)
"""

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional

from .board import Board, Position
from .player import Player
from .wall import Wall, WallManager, Orientation
from .move_validator import MoveValidator
from .pathfinder import Pathfinder


class GameStatus(Enum):
    """게임 상태"""
    IN_PROGRESS = "in_progress"
    PLAYER1_WIN = "player1_win"    # Player 1 승리
    PLAYER2_WIN = "player2_win"    # Player 2 / AI 승리
    ABANDONED = "abandoned"


class GameMode(Enum):
    """게임 모드"""
    VS_AI = "vs_ai"
    LOCAL_2P = "local_2p"


class ActionType(Enum):
    """액션 타입"""
    MOVE = "move"
    WALL = "wall"


@dataclass
class Action:
    """게임 액션"""
    action_type: ActionType
    row: int
    col: int
    orientation: Optional[Orientation] = None

    def to_dict(self) -> dict:
        result = {
            "type": self.action_type.value,
            "row": self.row,
            "col": self.col
        }
        if self.orientation:
            result["orientation"] = self.orientation.value
        return result


class GameState:
    """쿼리도 게임 상태 관리"""

    def __init__(
        self,
        game_id: Optional[str] = None,
        player1_name: str = "Player",
        player2_name: str = "AI",
        game_mode: str = "vs_ai"
    ):
        self.game_id = game_id or str(uuid.uuid4())
        self.status = GameStatus.IN_PROGRESS
        self.current_turn = 1  # 1 또는 2
        self.turn_count = 0
        self.winner: Optional[int] = None
        self.game_mode = GameMode(game_mode)

        # 플레이어 생성
        self.player1 = Player.create_player1(player1_name)
        self.player2 = Player.create_player2(player2_name)

        # 벽 관리자
        self.wall_manager = WallManager()

        # 타임스탬프
        self.created_at = datetime.utcnow()
        self.updated_at = datetime.utcnow()

    @property
    def current_player(self) -> Player:
        """현재 턴인 플레이어 반환"""
        return self.player1 if self.current_turn == 1 else self.player2

    @property
    def opponent_player(self) -> Player:
        """상대 플레이어 반환"""
        return self.player2 if self.current_turn == 1 else self.player1

    def get_valid_pawn_moves(self) -> list[Position]:
        """현재 플레이어의 유효한 폰 이동 목록"""
        return MoveValidator.get_valid_pawn_moves(
            self.current_player,
            self.opponent_player,
            self.wall_manager
        )

    def get_valid_wall_placements(self) -> list[Wall]:
        """현재 플레이어의 유효한 벽 설치 목록"""
        return MoveValidator.get_valid_wall_placements(
            self.current_player,
            self.opponent_player,
            self.wall_manager
        )

    def move_pawn(self, row: int, col: int) -> tuple[bool, str]:
        """
        현재 플레이어의 폰 이동

        Args:
            row: 목표 행
            col: 목표 열

        Returns:
            (성공 여부, 메시지)
        """
        if self.status in (GameStatus.PLAYER1_WIN, GameStatus.PLAYER2_WIN):
            return False, "Game is already finished"

        try:
            target = Position(row, col)
        except ValueError as e:
            return False, str(e)

        if not MoveValidator.is_valid_pawn_move(
            self.current_player,
            self.opponent_player,
            target,
            self.wall_manager
        ):
            return False, "Invalid move"

        # 이동 수행
        self.current_player.move_to(target)
        self.updated_at = datetime.utcnow()

        # 승리 확인
        if self.current_player.has_reached_goal():
            self.winner = self.current_turn
            self.status = GameStatus.PLAYER1_WIN if self.current_turn == 1 else GameStatus.PLAYER2_WIN
            return True, f"Player {self.current_turn} wins!"

        # 턴 전환
        self._switch_turn()

        return True, "Pawn moved successfully"

    def place_wall(self, row: int, col: int, orientation: str) -> tuple[bool, str]:
        """
        현재 플레이어가 벽 설치

        Args:
            row: 벽 시작 행
            col: 벽 시작 열
            orientation: "horizontal" 또는 "vertical"

        Returns:
            (성공 여부, 메시지)
        """
        if self.status in (GameStatus.PLAYER1_WIN, GameStatus.PLAYER2_WIN):
            return False, "Game is already finished"

        if not self.current_player.has_walls():
            return False, "No walls remaining"

        try:
            wall_orientation = Orientation(orientation)
            wall = Wall(row, col, wall_orientation)
        except (ValueError, KeyError) as e:
            return False, f"Invalid wall parameters: {e}"

        if not MoveValidator.is_valid_wall_placement(
            wall,
            self.current_player,
            self.opponent_player,
            self.wall_manager
        ):
            return False, "Invalid wall placement"

        # 벽 설치
        self.wall_manager.add_wall(wall)
        self.current_player.use_wall()
        self.updated_at = datetime.utcnow()

        # 턴 전환
        self._switch_turn()

        return True, "Wall placed successfully"

    def _switch_turn(self) -> None:
        """턴 전환"""
        self.current_turn = 2 if self.current_turn == 1 else 1
        self.turn_count += 1

    def get_player_distance_to_goal(self, player_id: int) -> int:
        """플레이어의 목표까지 최단 거리"""
        player = self.player1 if player_id == 1 else self.player2
        return Pathfinder.get_shortest_distance(
            player.position,
            player.goal_row,
            self.wall_manager
        )

    def copy(self) -> "GameState":
        """게임 상태 깊은 복사"""
        new_state = GameState.__new__(GameState)
        new_state.game_id = self.game_id
        new_state.status = self.status
        new_state.current_turn = self.current_turn
        new_state.turn_count = self.turn_count
        new_state.winner = self.winner
        new_state.game_mode = self.game_mode
        new_state.player1 = self.player1.copy()
        new_state.player2 = self.player2.copy()
        new_state.wall_manager = self.wall_manager.copy()
        new_state.created_at = self.created_at
        new_state.updated_at = self.updated_at
        return new_state

    def to_dict(self) -> dict:
        """게임 상태를 딕셔너리로 변환"""
        return {
            "game_id": self.game_id,
            "status": self.status.value,
            "game_mode": self.game_mode.value,
            "current_turn": self.current_turn,
            "turn_count": self.turn_count,
            "players": {
                "player1": {
                    "name": self.player1.name,
                    "position": {
                        "row": self.player1.position.row,
                        "col": self.player1.position.col
                    },
                    "walls_remaining": self.player1.walls_remaining,
                    "goal_row": self.player1.goal_row
                },
                "player2": {
                    "name": self.player2.name,
                    "position": {
                        "row": self.player2.position.row,
                        "col": self.player2.position.col
                    },
                    "walls_remaining": self.player2.walls_remaining,
                    "goal_row": self.player2.goal_row
                }
            },
            "walls": [wall.to_dict() for wall in self.wall_manager.walls],
            "winner": self.winner,
            "created_at": self.created_at.isoformat() + "Z",
            "updated_at": self.updated_at.isoformat() + "Z"
        }

    @classmethod
    def from_dict(cls, data: dict) -> "GameState":
        """딕셔너리에서 게임 상태 복원"""
        game = cls.__new__(cls)
        game.game_id = data["game_id"]

        # 하위 호환성: 기존 "finished" 상태 처리
        status_str = data["status"]
        if status_str == "finished":
            winner = data.get("winner")
            status_str = "player1_win" if winner == 1 else "player2_win"
        game.status = GameStatus(status_str)

        game.game_mode = GameMode(data.get("game_mode", "vs_ai"))
        game.current_turn = data["current_turn"]
        game.turn_count = data["turn_count"]
        game.winner = data.get("winner")

        # 플레이어 복원
        p1_data = data["players"]["player1"]
        game.player1 = Player(
            player_id=1,
            name=p1_data["name"],
            position=Position(p1_data["position"]["row"], p1_data["position"]["col"]),
            walls_remaining=p1_data["walls_remaining"]
        )

        p2_data = data["players"]["player2"]
        game.player2 = Player(
            player_id=2,
            name=p2_data["name"],
            position=Position(p2_data["position"]["row"], p2_data["position"]["col"]),
            walls_remaining=p2_data["walls_remaining"]
        )

        # 벽 복원
        game.wall_manager = WallManager()
        for wall_data in data.get("walls", []):
            wall = Wall.from_dict(wall_data)
            game.wall_manager.add_wall(wall)

        # 타임스탬프 복원
        game.created_at = datetime.fromisoformat(data["created_at"].rstrip("Z"))
        game.updated_at = datetime.fromisoformat(data["updated_at"].rstrip("Z"))

        return game
