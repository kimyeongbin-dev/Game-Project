"""
WS 레이트 리밋 (M3 7단계 판단 7, 6단계 검토 H8 나머지)

차례 아닌 행동을 연타해 게임 락을 붙잡거나, 재접속을 연타해 `mark_connected` 로 락을 잡는 경로를 막는다.

| 대상 | 저장소 | 초과 시 |
| :-- | :-- | :-- |
| 메시지 | 소켓별 토큰 버킷(프로세스 안 — 메시지마다 Redis 왕복 없음) | `rate_limit_exceeded`, 처리·락 없음 |
| 지속 위반 | 소켓별 누적 | close 1008 |
| 접속 | 유저별 분당 카운터(리미터 DB, 워커 공통) | 인증 직후 close 1013 — `mark_connected` 전 |

같은 계정 연결은 클러스터에 하나(4000 교체)라 소켓별 버킷이 사실상 유저 단위다. 다른 워커로 다시 붙어 버킷을 초기화하는
경로는 접속 카운터가 막는다. 리미터 Redis 장애는 허용(fail-open) — 멀티플레이 자체는 앱 Redis 가 막는다.
"""

import logging
import time
from typing import Callable

from redis.exceptions import RedisError

from app.core.config import settings
from app.db import redis_keys as keys
from app.db.redis import get_limiter_redis

logger = logging.getLogger(__name__)

WINDOW_SEC = 60


def _monotonic() -> float:
    return time.monotonic()


class TokenBucket:
    """용량 burst, 초당 rate 회복. 단조 시계를 주입한다(테스트)"""

    def __init__(self, burst: int, per_sec: float, clock: Callable[[], float] = _monotonic):
        self.burst, self.per_sec, self._clock = burst, per_sec, clock
        self.tokens = float(burst)
        self._at = clock()
        self.violations = 0

    def allow(self) -> bool:
        now = self._clock()
        self.tokens = min(self.burst, self.tokens + (now - self._at) * self.per_sec)
        self._at = now
        if self.tokens >= 1:
            self.tokens -= 1
            return True
        self.violations += 1
        return False

    @property
    def exhausted(self) -> bool:
        """위반이 쌓였다 — 연결을 닫는다(1008)"""
        return self.violations >= settings.ws_violation_close


def message_bucket(clock: Callable[[], float] = _monotonic) -> TokenBucket:
    return TokenBucket(settings.ws_msg_burst, settings.ws_msg_per_sec, clock)


class ConnectLimiter:
    """유저별 분당 접속 수 — 리미터 DB 의 고정 창 INCR"""

    async def allow(self, user_id: int) -> bool:
        client = get_limiter_redis()
        if client is None:
            return True
        key = keys.ws_connect_rate(user_id)
        try:
            count = await client.incr(key)
            if count == 1:
                await client.expire(key, WINDOW_SEC)
        except RedisError as exc:
            logger.warning("WS connect limiter unavailable (allowing): %s", exc)
            return True
        return count <= settings.ws_connect_per_minute


connect_limiter = ConnectLimiter()
