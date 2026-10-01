"""
Quoridor Service — 과도기 shim (M3 1단계 ~ 3단계)

구 REST `/api/v1/quoridor/*` 는 M3 1단계에서 폐기했다 (docs/api/platform.md §6).
남은 것은 `app/ws/ws_game.py` 가 import 하는 메서드 4개뿐이다.

- 게임 상태는 프로세스 메모리에만 있다. DB 에 쓰지 않는다 — 진행 중 상태의 권위는
  Redis `game:<id>:state` 이며(docs/api/games/maze.md §8), 3단계에서 이 모듈을
  Redis 저장소로 통째로 교체한다
- `ws_game` 은 라우터 미등록이라 실행 경로가 없다
"""

from typing import Optional

from app.games.maze import GameState


class QuoridorService:
    """게임 상태 보관 shim (프로세스 메모리)"""

    def __init__(self):
        self._games: dict[str, GameState] = {}

    async def create_game(self, game_mode: str = "local_2p") -> GameState:
        """새 게임 생성"""
        game = GameState(game_mode=game_mode)
        self._games[game.game_id] = game
        return game

    async def get_game(self, game_id: str) -> Optional[GameState]:
        """게임 조회"""
        return self._games.get(game_id)

    async def move_pawn(
        self, game_id: str, row: int, col: int
    ) -> tuple[bool, str, Optional[GameState]]:
        """현재 차례 좌석의 말 이동. (성공 여부, 메시지, 게임 상태)"""
        game = self._games.get(game_id)
        if not game:
            return False, "Game not found", None

        success, message = game.move_pawn(row, col)
        return success, message, game if success else None

    async def place_wall(
        self, game_id: str, row: int, col: int, orientation: str
    ) -> tuple[bool, str, Optional[GameState]]:
        """현재 차례 좌석의 벽 설치. (성공 여부, 메시지, 게임 상태)"""
        game = self._games.get(game_id)
        if not game:
            return False, "Game not found", None

        success, message = game.place_wall(row, col, orientation)
        return success, message, game if success else None


# 싱글톤 인스턴스
quoridor_service = QuoridorService()
