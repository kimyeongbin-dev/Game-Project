"""
워커별 이벤트 구독 버스 — Redis Pub/Sub → 이 프로세스의 소켓 (M3 4단계)

서비스가 상태를 쓴 직후 발행한 이벤트(`app/services/events.py`)를 받아, 수신자 중
**이 워커에 연결된 유저에게만** 보낸다. 소켓과 연결 맵은 프로세스 안에 있고, 누가 받을지는
이벤트의 수신자 목록(발행자가 Redis 에서 읽은 값)이 정한다.

- **패턴 구독 하나.** 게임·방이 생길 때마다 구독하지 않는다. 동적 구독은 유저가 붙은 직후
  SUBSCRIBE 가 끝나기 전의 메시지를 잃고, 채널별 참조 카운트(사실상 프로세스 내 소속 맵)가
  필요하다. 턴제라 이벤트가 적어 모든 워커가 전부 받아도 싸다
- **끊김 → 재구독 → 재동기화.** 구독이 끊기면 redis-py 는 `ConnectionError` 를 던지고,
  재구독 전까지의 메시지는 영구 유실된다(실측 E5). 지수 백오프로 다시 구독한 **직후**
  로컬 유저 전원에게 Redis 의 현재 상태를 보낸다. 이벤트에 권위가 없으므로 이것으로 수렴한다
- 수신 루프는 메시지 하나가 깨져도, 전송 하나가 실패해도 죽지 않는다

lifespan 배선(start/stop)과 /health 보고는 7단계에서 WS 라우터와 함께 한다.
"""

import asyncio
import logging
import secrets
from typing import Optional

from redis.exceptions import RedisError

from app.core.config import settings
from app.db import redis_keys as keys
from app.db.redis import new_pubsub_client
from app.db.redis_lock import require_redis
from app.services.events import Event
from app.ws.connection_manager import ConnectionManager
from app.ws.delivery import Delivery

logger = logging.getLogger(__name__)

CLIENT_NAME_PREFIX = "gamemoa-bus-"


class EventBus:
    def __init__(self, manager: ConnectionManager, delivery: Delivery):
        self._manager = manager
        self._delivery = delivery
        self.name = f"{CLIENT_NAME_PREFIX}{secrets.token_hex(4)}"
        self._task: Optional[asyncio.Task] = None
        self._subscribed = asyncio.Event()
        self.resubscribes = 0  # 재구독 성공 횟수 — 관측·테스트용

    @property
    def subscribed(self) -> bool:
        return self._subscribed.is_set()

    async def start(self) -> None:
        """구독 루프를 띄우고 첫 구독이 될 때까지 기다린다(상한 = 연결 타임아웃)

        Redis 가 꺼져 있으면 StoreUnavailable. 첫 구독이 늦어도 루프는 계속 재시도한다.
        """
        require_redis()
        if self._task is not None:
            return
        self._task = asyncio.create_task(self._run(), name=self.name)
        try:
            await self.wait_subscribed(settings.redis_socket_connect_timeout)
        except asyncio.TimeoutError:
            logger.warning("Event bus %s: first subscribe still pending", self.name)

    async def stop(self) -> None:
        task, self._task = self._task, None
        if task is None:
            return
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        self._subscribed.clear()

    async def wait_subscribed(self, timeout: float) -> None:
        await asyncio.wait_for(self._subscribed.wait(), timeout)

    # ----- 루프 -----

    async def _run(self) -> None:
        delay_ms = settings.pubsub_reconnect_min_ms
        resync_after_subscribe = False  # 첫 구독에는 보낼 소켓이 없다
        patterns = keys.event_patterns()

        while True:
            client = new_pubsub_client(self.name)
            pubsub = client.pubsub()
            try:
                await pubsub.psubscribe(*patterns)
                await self._await_confirmations(pubsub, len(patterns))
                self._subscribed.set()
                if resync_after_subscribe:
                    self.resubscribes += 1
                    logger.info("Event bus %s resubscribed — resyncing local sockets", self.name)
                    await self._resync_all()
                delay_ms = settings.pubsub_reconnect_min_ms

                while True:
                    message = await pubsub.get_message(timeout=1.0)
                    if message is not None and message["type"] == "pmessage":
                        await self._dispatch(message["data"])
            except (RedisError, OSError) as exc:
                self._subscribed.clear()
                resync_after_subscribe = True
                logger.warning("Event bus %s lost subscription: %s — retry in %dms",
                               self.name, exc, delay_ms)
            finally:
                await _close_quietly(pubsub, client)

            await asyncio.sleep(delay_ms / 1000)
            delay_ms = min(delay_ms * 2, settings.pubsub_reconnect_max_ms)

    @staticmethod
    async def _await_confirmations(pubsub, expected: int) -> None:
        """PSUBSCRIBE 확인이 다 올 때까지 읽는다 — 그 뒤 발행된 것은 반드시 받는다"""
        confirmed = 0
        while confirmed < expected:
            message = await pubsub.get_message(timeout=settings.redis_socket_connect_timeout)
            if message is None:
                raise TimeoutError("psubscribe confirmation timed out")
            if message["type"] == "psubscribe":
                confirmed += 1

    async def _dispatch(self, raw: str) -> None:
        try:
            event = Event.from_json(raw)
        except Exception:
            logger.warning("Event bus %s: undecodable message dropped: %.200r", self.name, raw)
            return

        local = self._manager.local_user_ids()
        for user_id in event.recipients:
            if user_id not in local:
                continue
            try:
                messages = await self._delivery.deliver(event, user_id)
            except Exception:
                # 상태 읽기 실패 등 — 이 유저만 건너뛴다. 다음 이벤트·재동기화가 메운다
                logger.exception("Event bus %s: deliver %s to %s failed", self.name, event.kind, user_id)
                continue
            for message in messages:
                await self._manager.send_personal(user_id, message)

    async def _resync_all(self) -> None:
        for user_id in sorted(self._manager.local_user_ids()):
            try:
                messages = await self._delivery.resync(user_id)
            except Exception:
                logger.exception("Event bus %s: resync of %s failed", self.name, user_id)
                continue
            for message in messages:
                await self._manager.send_personal(user_id, message)


async def _close_quietly(pubsub, client) -> None:
    for closable in (pubsub, client):
        try:
            await closable.aclose()
        except Exception as exc:  # 이미 끊긴 연결 — 정리 실패로 루프를 죽이지 않는다
            logger.debug("Event bus close failed: %s", exc)
