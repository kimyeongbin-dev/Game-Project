"""
1인칭 미로 대결 - 서버 권위 판정 엔진.

PLATFORM_ARCHITECTURE.md §4.1 대응:
- 이동/벽 설치 유효성 검증
- 벽 설치 시 모든 생존 좌석의 목표 도달 경로 존재 검증 (BFS)
- (예정) 3×3 시야 + 벽 차폐 필터링 (docs/api/games/maze.md §6)

좌석 수를 가정하지 않는다. 인원·시작점·목표·벽 수는 core/layouts.py 의 모드별
배치 테이블 값이며, 새 모드는 행 추가로 끝난다 (docs/api/platform.md §5).

NOTE: 모듈·클래스 명칭 일부(quoridor_service 등)는 구 Quoridor 구현을 유지한
      상태다. 도메인 리네이밍은 M3 3단계에서 서비스를 Redis 저장소로 교체할 때 한다.
"""

from .core.game_state import GameState
from .core.player import Player
from .core.wall import Wall
from .core.board import Board, Goal
from .core.layouts import LAYOUTS
from .core.move_validator import MoveValidator, Rejection
from .core.pathfinder import Pathfinder
from .ai.simple_ai import SimpleAI

__all__ = [
    "GameState",
    "Player",
    "Wall",
    "Board",
    "Goal",
    "LAYOUTS",
    "MoveValidator",
    "Rejection",
    "Pathfinder",
    "SimpleAI",
]
