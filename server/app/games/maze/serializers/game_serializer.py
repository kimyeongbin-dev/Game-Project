"""
Game Serializer Module
게임 상태 JSON 직렬화/역직렬화
"""

import json
from typing import Optional, List
from dataclasses import dataclass

from ..core.game_state import GameState


@dataclass


@dataclass


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


