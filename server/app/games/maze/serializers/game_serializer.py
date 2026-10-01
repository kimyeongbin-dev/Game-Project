"""
Game Serializer Module
게임 상태 JSON 직렬화/역직렬화

JSON 문자열이 Redis `game:<id>:state` 에 저장되는 값이다 (maze.md §8).
형태 자체는 GameState.to_dict() 가 정한다 — 여기서 따로 정의하지 않는다.
"""

import json
from typing import Optional

from ..core.game_state import GameState


class GameSerializer:
    """게임 상태 직렬화/역직렬화"""

    @staticmethod
    def to_json(game_state: GameState, indent: Optional[int] = None) -> str:
        """게임 상태를 JSON 문자열로 변환"""
        return json.dumps(game_state.to_dict(), indent=indent, ensure_ascii=False)

    @staticmethod
    def from_json(json_str: str) -> GameState:
        """JSON 문자열에서 게임 상태 복원. schema_version 이 다르면 ValueError"""
        return GameState.from_dict(json.loads(json_str))
