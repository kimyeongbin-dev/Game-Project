"""
1인칭 미로 대결 - 서버 권위 판정 엔진.

PLATFORM_ARCHITECTURE.md §4.1 대응:
- 이동/벽 설치 유효성 검증
- 벽 설치 시 모든 플레이어의 목표 도달 경로 존재 검증 (BFS)
- (예정) 플레이어 좌표·시선 기준 시야(Raycasting) 필터링

NOTE: 클래스/함수 명칭은 구 Quoridor 구현을 그대로 유지한 상태이며,
      도메인 리네이밍은 API 설계서 확정 단계에서 진행한다.
"""

from .core.game_state import GameState
from .core.player import Player
from .core.wall import Wall
from .core.board import Board
from .core.move_validator import MoveValidator
from .core.pathfinder import Pathfinder
from .ai.simple_ai import SimpleAI

__all__ = [
    "GameState",
    "Player",
    "Wall",
    "Board",
    "MoveValidator",
    "Pathfinder",
    "SimpleAI",
]
