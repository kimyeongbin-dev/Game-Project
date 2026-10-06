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
from dataclasses import dataclass
from typing import Optional

from app.core.config import settings
from app.core.time import Clock, redis_clock
from app.core.worker import WORKER_ID
from app.db import redis_keys as keys
from app.db.redis import get_redis
from app.db.redis_lock import StoreUnavailable
from app.services.maze_game import GameBusy, GameNotFound, MazeGameService
from app.services.sweeper import DeadlineSweeper
from app.ws.bus import EventBus
from app.ws.connection_manager import ConnectionManager
from app.ws.delivery import Delivery
from app.ws.maze_handler import USER_CONN_TTL_SEC, MazeSocketHandler, Session, maze_handler
from app.ws.server_grace import RecentDisconnects, apply_on_shutdown

logger = logging.getLogger(__name__)

_SIGNALS = (signal.SIGTERM, signal.SIGINT)


def _monotonic_ms() -> int:
    return time.monotonic_ns() // 1_000_000


RETRY_INTERVAL_SEC = 1.0
# 밀려난(4000) 연결의 끊김 확인을 미루는 시간 — 새 연결이 좌석 소유를 가져가기에 충분하다(접속 처리는 수 ms)
REPLACE_SETTLE_SEC = 3.0


@dataclass
class PendingDisconnect:
    """아직 기록하지 못한 끊김 — 원래 시각(단조)과 끊긴 연결 id 를 들고 다시 시도한다 (검토 H4·R1·R2·R3)"""
    game_id: Optional[str]          # 활동을 아직 못 읽었으면 None
    user_id: int
    at_mono_ms: int
    conn_id: str
    not_before_mono_ms: int = 0     # 밀려난 연결은 새 연결이 자리 잡을 때까지 기다린다
    session: Optional[Session] = None   # 연결 표시(user:{uid}:conn) 해제에 실패했으면 다시 지운다(독립 검토 #2 Q10)


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
        # 붙어 있는 동안 연결 표시(user:{uid}:conn)의 안전망 TTL 을 늘린다 — 하루 넘는 연결도 표시를 잃지 않는다(독립 검토 #2 Q10)
        async with client.pipeline(transaction=False) as pipe:
            for user_id in users:
                pipe.expire(keys.user_conn(user_id), USER_CONN_TTL_SEC)
            await pipe.execute()
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
        self.pending: list[PendingDisconnect] = []
        self._retry_task: Optional[asyncio.Task] = None
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
        await self._stop_retry()
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
        """핸들러가 소켓 종료 때 부른다 — 밀려난(4000) 연결도. 처리는 추적되는 태스크로

        좌석 owner 는 연결 id 다(검토 R1). 그래서 기록은 언제나 "끊긴 그 연결이 아직 좌석의 연결일 때만" 일어난다 —
        그 사이 같은 계정이 (같은 워커든 다른 워커든) 다시 붙었으면 서비스가 무시한다.
        """
        task = asyncio.create_task(self._record_disconnect(session, close_code))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        await asyncio.shield(task)

    async def _record_disconnect(self, session: Session, close_code: Optional[int]) -> None:
        at_mono = self._monotonic_ms()
        item = PendingDisconnect(None, session.user_id, at_mono, session.conn.conn_id)
        if not await self.handler.release_session(session):
            item.session = session
        if session.conn.replaced:
            # 밀려난 연결 — 보통은 새 연결이 이미 좌석을 가져갔다(그러면 아래 기록은 무시된다). 새 연결이 소유를 못 가져간
            # 채 끝났으면(검토 R3) 이 기록이 끊김을 남긴다. 새 연결이 자리 잡을 시간을 주고 확인한다
            item.not_before_mono_ms = at_mono + int(REPLACE_SETTLE_SEC * 1000)
            self._defer(item)
            return
        if not await self._try_record(item, first=True):
            self._defer(item)

    async def _try_record(self, item: PendingDisconnect, *, first: bool) -> bool:
        """한 번 시도. 끝났으면(기록·무시·게임 없음) True, 다시 시도해야 하면 False"""
        if item.session is not None:
            # 연결 표시를 먼저 지운다 — 남아 있으면 그 연결이 아직 붙어 있는 것으로 보여 끊김 기록이 걸러진다(Q2 대조)
            if not await self.handler.release_session(item.session):
                return False
            item.session = None
        try:
            if item.game_id is None:  # 활동 읽기도 실패할 수 있다(Redis 순간 장애 — 검토 R2)
                kind, rest = await self.handler._activity(item.user_id)
                if kind != "game":
                    return True
                item.game_id = rest
            if first:
                result = await self.games.mark_disconnected(item.game_id, item.user_id, owner=item.conn_id)
            else:
                at_ms = await self._clock.now_ms() - (self._monotonic_ms() - item.at_mono_ms)
                result = await self.games.redo_disconnect(item.game_id, item.user_id, owner=item.conn_id, at_ms=at_ms)
        except (GameBusy, StoreUnavailable) as exc:
            logger.info("Disconnect of %s deferred: %s", item.user_id, exc)
            return False
        except GameNotFound:
            return True
        except Exception:
            logger.exception("Could not record disconnect of %s in %s", item.user_id, item.game_id)
            return False
        if result is not None:
            self.recent.record(item.game_id, item.user_id, result.disconnected_at_ms)
        return True

    # ----- 끊김 재시도 (검토 H4·R1·R2·R3) -----

    def _defer(self, item: PendingDisconnect) -> None:
        self.pending.append(item)
        if self._retry_task is None or self._retry_task.done():
            self._retry_task = asyncio.create_task(self._retry_loop(), name="disconnect-retry")

    async def _retry_loop(self) -> None:
        while self.pending:
            await asyncio.sleep(RETRY_INTERVAL_SEC)
            await self.retry_pending()

    async def retry_pending(self, *, force: bool = False) -> int:
        """밀린 끊김을 원래 시각으로 다시 기록한다. 끝낸 수

        상한(disconnect_retry_max_sec)이 지나면 버린다 — 그만큼 Redis 가 안 되면 장기 장애 무효(§8)가 그 게임을 닫고,
        락 경합만으로 120 s 를 넘기는 일은 없다. force: 정착 시간을 기다리지 않는다(종료 직전).
        """
        done = 0
        still: list[PendingDisconnect] = []
        now_mono = self._monotonic_ms()
        for item in self.pending:
            if now_mono - item.at_mono_ms > settings.disconnect_retry_max_sec * 1000:
                logger.warning("Gave up recording disconnect of %s in %s", item.user_id, item.game_id)
                continue
            if not force and now_mono < item.not_before_mono_ms:
                still.append(item)
                continue
            if await self._try_record(item, first=False):
                done += 1
            else:
                still.append(item)
        self.pending = still
        return done

    async def _stop_retry(self) -> None:
        task, self._retry_task = self._retry_task, None
        if task is not None:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        if self.pending:  # 종료 전에 한 번 더 — 정착 시간을 기다리지 않는다
            await self.retry_pending(force=True)

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
