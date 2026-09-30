"""
Game Serializer Module
게임 상태 JSON 직렬화/역직렬화 및 리플레이 지원
"""

import json
from typing import Optional, List
from dataclasses import dataclass

from ..core.game_state import GameState


@dataclass
class MoveRecord:
    """수 기록"""
    step_no: int
    player: int
    action_type: str  # "move" or "wall"
    row: int
    col: int
    orientation: Optional[str] = None  # wall일 때만

    def to_dict(self) -> dict:
        result = {
            "step_no": self.step_no,
            "player": self.player,
            "action_type": self.action_type,
            "row": self.row,
            "col": self.col,
        }
        if self.orientation:
            result["orientation"] = self.orientation
        return result

    @classmethod
    def from_dict(cls, data: dict) -> "MoveRecord":
        return cls(
            step_no=data["step_no"],
            player=data["player"],
            action_type=data["action_type"],
            row=data["row"],
            col=data["col"],
            orientation=data.get("orientation")
        )


@dataclass
class ReplayData:
    """리플레이 데이터"""
    game_id: str
    player1_name: str
    player2_name: str
    game_mode: str
    moves: List[MoveRecord]
    final_status: str
    winner: Optional[int]

    def to_dict(self) -> dict:
        return {
            "game_id": self.game_id,
            "player1_name": self.player1_name,
            "player2_name": self.player2_name,
            "game_mode": self.game_mode,
            "moves": [move.to_dict() for move in self.moves],
            "total_moves": len(self.moves),
            "final_status": self.final_status,
            "winner": self.winner
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ReplayData":
        return cls(
            game_id=data["game_id"],
            player1_name=data["player1_name"],
            player2_name=data["player2_name"],
            game_mode=data["game_mode"],
            moves=[MoveRecord.from_dict(m) for m in data["moves"]],
            final_status=data["final_status"],
            winner=data.get("winner")
        )


class GameSerializer:
    """게임 상태 직렬화/역직렬화"""

    @staticmethod
    def to_json(game_state: GameState, indent: Optional[int] = None) -> str:
        """게임 상태를 JSON 문자열로 변환"""
        return json.dumps(game_state.to_dict(), indent=indent, ensure_ascii=False)

    @staticmethod
    def from_json(json_str: str) -> GameState:
        """JSON 문자열에서 게임 상태 복원"""
        data = json.loads(json_str)
        return GameState.from_dict(data)

    @staticmethod
    def to_dict(game_state: GameState) -> dict:
        """게임 상태를 딕셔너리로 변환"""
        return game_state.to_dict()

    @staticmethod
    def from_dict(data: dict) -> GameState:
        """딕셔너리에서 게임 상태 복원"""
        return GameState.from_dict(data)

    @staticmethod
    def save_to_file(game_state: GameState, filepath: str) -> None:
        """게임 상태를 파일에 저장"""
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(GameSerializer.to_json(game_state, indent=2))

    @staticmethod
    def load_from_file(filepath: str) -> GameState:
        """파일에서 게임 상태 로드"""
        with open(filepath, "r", encoding="utf-8") as f:
            return GameSerializer.from_json(f.read())

    # ===== 리플레이 관련 메서드 =====

    @staticmethod
    def replay_to_json(replay_data: ReplayData, indent: Optional[int] = None) -> str:
        """리플레이 데이터를 JSON으로 변환"""
        return json.dumps(replay_data.to_dict(), indent=indent, ensure_ascii=False)

    @staticmethod
    def replay_from_json(json_str: str) -> ReplayData:
        """JSON에서 리플레이 데이터 복원"""
        data = json.loads(json_str)
        return ReplayData.from_dict(data)

    @staticmethod
    def create_initial_state(player1_name: str = "Player", player2_name: str = "AI") -> dict:
        """초기 게임 상태 생성"""
        return {
            "status": "in_progress",
            "current_turn": 1,
            "turn_count": 0,
            "players": {
                "player1": {
                    "name": player1_name,
                    "position": {"row": 8, "col": 4},
                    "walls_remaining": 10,
                    "goal_row": 0
                },
                "player2": {
                    "name": player2_name,
                    "position": {"row": 0, "col": 4},
                    "walls_remaining": 10,
                    "goal_row": 8
                }
            },
            "walls": [],
            "winner": None
        }

    @staticmethod
    def apply_move_to_state(state: dict, move: MoveRecord) -> dict:
        """
        상태에 수를 적용하여 새로운 상태 반환
        (실제 게임 로직 없이 간단히 상태만 업데이트)
        """
        import copy
        new_state = copy.deepcopy(state)

        player_key = "player1" if move.player == 1 else "player2"

        if move.action_type == "move":
            # 폰 이동
            new_state["players"][player_key]["position"] = {
                "row": move.row,
                "col": move.col
            }
        elif move.action_type == "wall":
            # 벽 설치
            new_state["walls"].append({
                "row": move.row,
                "col": move.col,
                "orientation": move.orientation
            })
            new_state["players"][player_key]["walls_remaining"] -= 1

        # 턴 전환
        new_state["current_turn"] = 2 if move.player == 1 else 1
        new_state["turn_count"] = move.step_no + 1

        return new_state

    @staticmethod
    def reconstruct_state_at_step(
        initial_state: dict,
        moves: List[MoveRecord],
        target_step: int
    ) -> dict:
        """
        특정 스텝에서의 상태를 재구성

        Args:
            initial_state: 초기 상태
            moves: 모든 수 목록
            target_step: 목표 스텝 번호 (-1이면 초기 상태)

        Returns:
            해당 스텝에서의 게임 상태
        """
        if target_step < 0:
            return initial_state

        import copy
        state = copy.deepcopy(initial_state)

        for move in moves:
            if move.step_no > target_step:
                break
            state = GameSerializer.apply_move_to_state(state, move)

        return state
