"""
1인칭 미로 대결 - 서버 권위 판정 엔진.

PLATFORM_ARCHITECTURE.md §4.1 대응:
- 이동/벽 설치 유효성 검증
- 벽 설치 시 모든 생존 좌석의 목표 도달 경로 존재 검증 (BFS)
- 3×3 시야 + 벽 차폐 + 좌석별 누적 관측 (core/vision.py, docs/api/games/maze.md §6)

좌석 수를 가정하지 않는다. 인원·시작점·목표·벽 수는 core/layouts.py 의 모드별
배치 테이블 값이며, 새 모드는 행 추가로 끝난다 (docs/api/platform.md §5).

Redis 저장·락·종료 기록은 app/services/maze_game.py 의 몫이다. 이 패키지는
프레임워크·저장소를 모른다.
"""

from .core.game_state import GameState
from .core.player import Player
from .core.wall import Wall
from .core.board import Board, Goal
from .core.layouts import LAYOUTS
from .core.move_validator import MoveValidator, Rejection
from .core.vision import SeatMemory, Sight, UnitEdge, game_sight, sight, unit_edges
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
    "SeatMemory",
    "Sight",
    "UnitEdge",
    "game_sight",
    "sight",
    "unit_edges",
]
