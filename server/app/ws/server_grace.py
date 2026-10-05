"""
서버 유예 후보 — 이 워커가 기록한 최근 끊김 (maze.md §8 "서버 유예", M3 6단계 판단 7)

배포(정상 종료)로 끊긴 좌석은 두 시계를 `server_grace_max_ms` 까지 멈춘다. 판별은 **서버가 종료
단계에 들어갔는가**로만 한다 — close code 1012 는 클라이언트도 보낼 수 있어 쓰지 않는다.

uvicorn 은 소켓을 먼저 닫고 lifespan shutdown 을 나중에 돈다(실측 E3). 그래서 끊김은 언제나 일반
끊김으로 기록하고(`mark_disconnected`), 이 워커가 기록한 것을 여기에도 남긴다. lifespan shutdown 이
`apply_on_shutdown` 으로 종료 직전 `server_grace_window_ms` 안의 끊김에 유예를 **소급**한다.
시계가 지연 정산이라 소급이 정확하다. 크래시는 lifespan 이 돌지 않으므로 면제되지 않는다(§8).

프로세스 로컬이다 — 그 워커의 종료만 그 워커의 끊김을 면제한다. 배선은 `app/ws/runtime.py`(M3 7단계).
"""

from collections import deque

from app.core.config import settings
from app.core.time import Clock, redis_clock
from app.services.maze_game import GraceEntry, MazeGameService, maze_games


class RecentDisconnects:
    """최근 끊김의 짧은 기록. 오래된 것은 기록할 때 버린다"""

    def __init__(self, keep_ms: int | None = None):
        self._keep_ms = keep_ms if keep_ms is not None else max(settings.server_grace_window_ms * 5, 10_000)
        self._entries: deque[GraceEntry] = deque()

    def record(self, game_id: str, user_id: int, disconnected_at_ms: int) -> None:
        self._entries.append(GraceEntry(game_id, user_id, disconnected_at_ms))
        while self._entries and self._entries[0].disconnected_at_ms < disconnected_at_ms - self._keep_ms:
            self._entries.popleft()

    def since(self, from_ms: int) -> list[GraceEntry]:
        return [e for e in self._entries if e.disconnected_at_ms >= from_ms]


async def apply_on_shutdown(
    recent: RecentDisconnects,
    *,
    draining_at_ms: int | None = None,
    games: MazeGameService = maze_games,
    clock: Clock = redis_clock,
) -> int:
    """lifespan shutdown 에서 부른다(Redis 를 닫기 전, 진행 중인 끊김 처리를 기다린 뒤). 적용한 좌석 수

    draining_at_ms: 종료 신호(SIGTERM)를 받은 시각(Redis TIME 기준, M3 7단계 검토 M9). 그 시각 − 창 이후의 끊김은
    전부 배포 끊김이다 — 끊김 처리가 늦거나 종료 중인 인스턴스로 재접속했다 다시 끊겨도(E4) 유예가 남는다.
    신호를 보지 못했으면(테스트·reload) 지금 시각이 기준이다.
    """
    anchor = draining_at_ms if draining_at_ms is not None else await clock.now_ms()
    return await games.apply_server_grace(recent.since(anchor - settings.server_grace_window_ms))
