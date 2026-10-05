"""
실시간 런타임 — 워커 하나의 WS 구성요소를 lifespan 에 묶는다 (M3 7단계 판단 6)

구독 버스·데드라인 스위퍼·큐 티커·최근 끊김(서버 유예 후보)·끊김 처리 태스크를 하나로 들고, 기동·종료 순서를 정한다.

```
startup : (Redis 있으면) bus.start → sweeper.start → queue_ticker.start → 종료 신호 훅
shutdown: (uvicorn 이 이미 1012 로 닫음) → 끊김 처리 태스크 대기(상한 server_grace_window_ms)
          → apply_on_shutdown(종료 신호 시각 기준) → queue_ticker.stop → sweeper.stop → bus.stop
```

이어서 main.py 가 Redis·DB 를 닫는다 — 서버 유예 소급은 Redis 를 닫기 전이어야 한다.

- **종료 신호 시각(검토 M9).** uvicorn 은 소켓을 먼저 닫고 lifespan 을 나중에 돈다(실측 E3). 끊김 처리가 늦거나 E4 처럼
  두 번 끊기면 lifespan 시각 기준 창 밖으로 밀린다. 그래서 uvicorn 이 설치한 SIGTERM/SIGINT 처리기를 감싸 **신호를 받은
  순간**(단조 시계)을 남기고, 종료 때 Redis TIME 으로 환산해 그 시각부터의 끊김을 전부 유예 대상으로 본다
- 끊김 처리는 추적되는 태스크다 — 종료가 그것을 기다린 뒤 유예를 소급한다(그 전에 소급하면 아직 기록 안 된 끊김이 빠진다)
- Redis 가 기동 시 없으면 아무것도 띄우지 않는다. 핸들러가 접속을 1013 으로 닫는다
"""

import asyncio
import logging
import signal
import threading
import time
from typing import Optional

from app.core.config import settings
from app.core.time import Clock, redis_clock
from app.core.worker import WORKER_ID
from app.db import redis_keys as keys
from app.db.redis import get_redis
from app.services.maze_game import MazeGameService, maze_games
from app.services.sweeper import DeadlineSweeper
from app.ws.bus import EventBus
from app.ws.connection_manager import ConnectionManager
from app.ws.delivery import Delivery
from app.ws.maze_handler import MazeSocketHandler, Session, maze_handler
from app.ws.server_grace import RecentDisconnects, apply_on_shutdown

logger = logging.getLogger(__name__)

_SIGNALS = (signal.SIGTERM, signal.SIGINT)


def _monotonic_ms() -> int:
    return time.monotonic_ns() // 1_000_000


class QueueTicker:
    """큐 대기자에게 주기적으로 queue_status (§3). 이 워커의 연결만, 활동은 MGET 한 번"""

    def __init__(self, manager: ConnectionManager, delivery: Delivery):
        self._manager = manager
        self._delivery = delivery
        self._task: Optional[asyncio.Task] = None

    async def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._loop(), name="queue-ticker")

    async def stop(self) -> None:
        task, self._task = self._task, None
        if task is not None:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

    async def _loop(self) -> None:
        while True:
            await asyncio.sleep(settings.queue_status_interval_sec)
            try:
                await self.tick()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Queue ticker failed")

    async def tick(self) -> int:
        users = sorted(self._manager.local_user_ids())
        client = get_redis()
        if not users or client is None:
            return 0
        values = await client.mget(*(keys.user_activity(u) for u in users))
        sent = 0
        for user_id, value in zip(users, values):
            if value is None or keys.parse_activity(value)[0] != "queue":
                continue
            for message in await self._delivery.resync(user_id):
                await self._manager.send_personal(user_id, message)
                sent += 1
        return sent


class Realtime:
    def __init__(
        self,
        handler: MazeSocketHandler = maze_handler,
        *,
        games: Optional[MazeGameService] = None,
        bus: Optional[EventBus] = None,
        sweeper: Optional[DeadlineSweeper] = None,
        ticker: Optional[QueueTicker] = None,
        clock: Clock = redis_clock,
        worker_id: str = WORKER_ID,
        monotonic_ms=_monotonic_ms,
    ):
        self.handler = handler
        self.games = games if games is not None else handler.games
        self.bus = bus if bus is not None else EventBus(handler.manager, handler.delivery)
        self.sweeper = sweeper if sweeper is not None else DeadlineSweeper(
            self.games, handler.matches, worker_id=worker_id)
        self.ticker = ticker if ticker is not None else QueueTicker(handler.manager, handler.delivery)
        self.recent = RecentDisconnects()
        self.worker_id = worker_id
        self._clock = clock
        self._monotonic_ms = monotonic_ms
        self._tasks: set[asyncio.Task] = set()
        self._draining_mono_ms: Optional[int] = None
        self._restore_signals: dict = {}
        self.started = False
        handler.on_disconnect = self.on_disconnect

    # ----- 수명 -----

    async def start(self) -> None:
        if get_redis() is None:
            logger.warning("Realtime disabled — Redis unavailable at startup (WS will close with 1013)")
            return
        await self.bus.start()
        await self.sweeper.start()
        await self.ticker.start()
        self._install_signal_hook()
        self.started = True
        logger.info("Realtime started (worker=%s)", self.worker_id)

    async def stop(self) -> None:
        if not self.started:
            return
        await self.drain_disconnects(settings.server_grace_window_ms / 1000)
        try:
            applied = await apply_on_shutdown(
                self.recent, draining_at_ms=await self.draining_at_ms(), games=self.games, clock=self._clock)
            logger.info("Server grace applied to %d seat(s)", applied)
        except Exception:
            logger.exception("Server grace on shutdown failed")
        await self.ticker.stop()
        await self.sweeper.stop()
        await self.bus.stop()
        self._uninstall_signal_hook()
        self.started = False

    async def drain_disconnects(self, timeout: float) -> None:
        """진행 중인 끊김 처리를 기다린다 — 그 전에 유예를 소급하면 아직 기록 안 된 끊김이 빠진다"""
        pending = [t for t in self._tasks if not t.done()]
        if not pending:
            return
        done, still = await asyncio.wait(pending, timeout=timeout)
        if still:
            logger.warning("%d disconnect task(s) still running at shutdown", len(still))

    # ----- 끊김 -----

    async def on_disconnect(self, session: Session, close_code: Optional[int]) -> None:
        """핸들러가 소켓 종료 때 부른다(밀려난 연결은 부르지 않는다). 처리는 추적되는 태스크로"""
        task = asyncio.create_task(self._record_disconnect(session, close_code))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        await asyncio.shield(task)

    async def _record_disconnect(self, session: Session, close_code: Optional[int]) -> None:
        game_id = await self.handler._current_game(session.user_id)
        if game_id is None:
            return
        try:
            result = await self.games.mark_disconnected(game_id, session.user_id)
        except Exception:
            logger.warning("Could not record disconnect of %s in %s", session.user_id, game_id)
            return
        if result is not None:
            self.recent.record(game_id, session.user_id, result.disconnected_at_ms)

    # ----- 종료 신호 (검토 M9) -----

    def mark_draining(self) -> None:
        if self._draining_mono_ms is None:
            self._draining_mono_ms = self._monotonic_ms()

    async def draining_at_ms(self) -> Optional[int]:
        """종료 신호를 받은 시각 — Redis TIME 기준으로 환산. 신호를 못 봤으면 None"""
        if self._draining_mono_ms is None:
            return None
        now = await self._clock.now_ms()
        return now - (self._monotonic_ms() - self._draining_mono_ms)

    def _install_signal_hook(self) -> None:
        if threading.current_thread() is not threading.main_thread():
            return  # 신호는 주 스레드에서만 설치할 수 있다(테스트 서버 스레드)
        for sig in _SIGNALS:
            previous = signal.getsignal(sig)

            def hook(signum, frame, previous=previous):
                self.mark_draining()
                if callable(previous):
                    previous(signum, frame)

            signal.signal(sig, hook)
            self._restore_signals[sig] = previous

    def _uninstall_signal_hook(self) -> None:
        for sig, previous in self._restore_signals.items():
            try:
                signal.signal(sig, previous)
            except (TypeError, ValueError):
                pass
        self._restore_signals.clear()

    # ----- 관측 -----

    def health(self) -> dict:
        return {
            "started": self.started,
            "worker_id": self.worker_id,
            "connections": len(self.handler.manager.local_user_ids()),
            "bus": {"name": self.bus.name, "subscribed": self.bus.subscribed,
                    "resubscribes": self.bus.resubscribes},
            "sweeper": {"running": self.sweeper.running, "last_tick_ok": self.sweeper.last_tick_ok,
                        "last_tick_at_ms": self.sweeper.last_tick_at_ms},
            "draining": self._draining_mono_ms is not None,
        }


realtime = Realtime()
