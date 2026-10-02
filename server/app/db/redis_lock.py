"""
Redis 락과 펜싱 쓰기 — 멀티플레이 상태의 직렬화.

게임 상태의 권위는 Redis 다 (docs/api/games/maze.md §8). 어느 워커든 행동을 받으면
게임별 락을 잡고 상태를 읽어 판정·기록한다. 매치·방도 같은 헬퍼를 쓴다.

- 획득: `SET key token NX PX ttl`. 실패하면 짧게 쉬며 `wait_ms` 까지 재시도한다
- 해제: 토큰이 아직 내 것일 때만 지운다 — TTL 로 풀린 뒤 남이 잡은 락을 지우지 않는다
- 펜싱 쓰기: 락 토큰이 아직 내 것일 때만 쓴다. 락 TTL 을 넘긴 행동이 다음 행동의
  결과를 덮어쓰지 못한다. 여러 키(게임 상태 + 좌석별 시야)는 한 번에 전부 또는 전무로 쓴다

`is_redis_available()` 는 기동 시 한 번 정해지는 값이라 런타임 장애를 잡지 못한다
(실측 E7). 그래서 `RedisError` 를 `StoreUnavailable` 로 바꾸는 `store_errors()` 를
함께 둔다. 멀티 경로는 둘 다 쓴다.
"""

import asyncio
import logging
import secrets
from contextlib import asynccontextmanager
from typing import AsyncIterator, Mapping, Optional

from redis.asyncio import Redis
from redis.exceptions import RedisError

from app.core.config import settings
from app.db.redis import get_redis, is_redis_available

logger = logging.getLogger(__name__)

_RETRY_INTERVAL_SEC = 0.01

_RELEASE_LUA = """
if redis.call('GET', KEYS[1]) == ARGV[1] then
    return redis.call('DEL', KEYS[1])
end
return 0
"""

# KEYS[1]=락, KEYS[2..]=대상 / ARGV[1]=토큰, ARGV[2]=EX 초('' 이면 없음), ARGV[3..]=값
# 스크립트 하나라 원자적이다 — 토큰이 내 것이면 대상 전부를, 아니면 아무것도 쓰지 않는다
_FENCED_MSET_LUA = """
if redis.call('GET', KEYS[1]) ~= ARGV[1] then
    return 0
end
for i = 2, #KEYS do
    if ARGV[2] == '' then
        redis.call('SET', KEYS[i], ARGV[i + 1])
    else
        redis.call('SET', KEYS[i], ARGV[i + 1], 'EX', ARGV[2])
    end
end
return 1
"""


class StoreUnavailable(Exception):
    """Redis 를 쓸 수 없다 — 기동 시 연결 실패 또는 런타임 장애"""


class LockTimeout(Exception):
    """락 대기 상한을 넘겼다"""


def require_redis() -> Redis:
    """멀티플레이 진입점 가드. 사용 불가면 StoreUnavailable"""
    client = get_redis()
    if not is_redis_available() or client is None:
        raise StoreUnavailable("Redis is not available")
    return client


@asynccontextmanager
async def store_errors() -> AsyncIterator[None]:
    """블록 안의 RedisError 를 StoreUnavailable 로 바꾼다"""
    try:
        yield
    except RedisError as exc:
        raise StoreUnavailable(str(exc)) from exc


@asynccontextmanager
async def redis_lock(
    redis: Redis,
    key: str,
    *,
    ttl_ms: Optional[int] = None,
    wait_ms: Optional[int] = None,
) -> AsyncIterator[str]:
    """락을 잡고 토큰을 넘긴다. 대기 상한을 넘기면 LockTimeout"""
    ttl_ms = settings.game_lock_ttl_ms if ttl_ms is None else ttl_ms
    wait_ms = settings.game_lock_wait_ms if wait_ms is None else wait_ms
    token = secrets.token_hex(16)

    loop = asyncio.get_running_loop()
    deadline = loop.time() + wait_ms / 1000
    async with store_errors():
        while not await redis.set(key, token, nx=True, px=ttl_ms):
            if loop.time() >= deadline:
                raise LockTimeout(key)
            await asyncio.sleep(_RETRY_INTERVAL_SEC)

    try:
        yield token
    finally:
        try:
            released = await redis.eval(_RELEASE_LUA, 1, key, token)
            if not released:
                logger.warning("Lock %s expired before release (ttl=%dms)", key, ttl_ms)
        except RedisError as exc:  # 해제 실패는 TTL 이 정리한다 — 본문 결과를 덮지 않는다
            logger.warning("Lock %s release failed: %s", key, exc)


async def fenced_set(
    redis: Redis,
    lock_key: str,
    token: str,
    key: str,
    value: str,
    *,
    ex: Optional[int] = None,
) -> bool:
    """락 토큰이 아직 내 것일 때만 key 에 쓴다. 썼으면 True"""
    return await fenced_mset(redis, lock_key, token, {key: value}, ex=ex)


async def fenced_mset(
    redis: Redis,
    lock_key: str,
    token: str,
    items: Mapping[str, str],
    *,
    ex: Optional[int] = None,
) -> bool:
    """락 토큰이 아직 내 것일 때만 items 전부를 같은 EX 로 쓴다(전부 또는 전무). 썼으면 True"""
    if not items:
        raise ValueError("fenced_mset needs at least one key")
    async with store_errors():
        written = await redis.eval(
            _FENCED_MSET_LUA, 1 + len(items), lock_key, *items.keys(),
            token, "" if ex is None else str(ex), *items.values(),
        )
    return bool(written)
