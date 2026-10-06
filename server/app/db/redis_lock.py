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
from typing import AsyncIterator, Mapping, Optional, Sequence

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

# KEYS[1]=락, KEYS[2..n+1]=대상 문자열, KEYS[n+2..]=ZSET 들
# ARGV[1]=토큰, ARGV[2]=EX 초('' 이면 없음), ARGV[3]=n, ARGV[4..3+n]=값, ARGV[4+n]=ZSET 개수 z,
#   이어서 ZSET 마다: m, (member, score)×m, k, member×k
# 스크립트 하나라 원자적이다 — 토큰이 내 것이면 전부를, 아니면 아무것도 쓰지 않는다
_FENCED_WRITE_LUA = """
if redis.call('GET', KEYS[1]) ~= ARGV[1] then
    return 0
end
local n = tonumber(ARGV[3])
for i = 1, n do
    if ARGV[2] == '' then
        redis.call('SET', KEYS[i + 1], ARGV[3 + i])
    else
        redis.call('SET', KEYS[i + 1], ARGV[3 + i], 'EX', ARGV[2])
    end
end
local p = 4 + n
local z = tonumber(ARGV[p])
for zi = 1, z do
    local key = KEYS[n + 1 + zi]
    local m = tonumber(ARGV[p + 1])
    for j = 1, m do
        redis.call('ZADD', key, ARGV[p + 1 + 2 * j], ARGV[p + 2 * j])
    end
    p = p + 1 + 2 * m
    local k = tonumber(ARGV[p + 1])
    for j = 1, k do
        redis.call('ZREM', key, ARGV[p + 1 + j])
    end
    p = p + 1 + k
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
            # 실행된 SET NX 의 응답만 잃고 재시도했으면 락은 이미 내 것이다 — 기다리다 스스로 교착하지 않는다(독립 검토 #2 Q5)
            if await redis.get(key) == token:
                break
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
    return await fenced_write(redis, lock_key, token, items, ex=ex)


ZsetOps = tuple[Mapping[str, int], Sequence[str]]  # (ZADD member→score, ZREM members)


async def fenced_write(
    redis: Redis,
    lock_key: str,
    token: str,
    items: Mapping[str, str],
    *,
    ex: Optional[int] = None,
    zset: Optional[str] = None,
    zadd: Optional[Mapping[str, int]] = None,
    zrem: Sequence[str] = (),
    zsets: Optional[Mapping[str, ZsetOps]] = None,
) -> bool:
    """락 토큰이 아직 내 것일 때만 items 를 쓰고 ZSET 들에 ZADD/ZREM 한다 — 전부 또는 전무. 썼으면 True

    게임 상태·시야·시계와 색인(데드라인, 워커별 좌석)을 한 번에 바꾸려고 둔다(M3 6단계). 나눠 쓰면 그 사이
    장애로 "턴은 바뀌었는데 데드라인이 없다" 가 남고, 그 게임은 영원히 만료되지 않는다.
    ZSET 하나는 zset/zadd/zrem 으로, 여럿은 zsets={key: (zadd, zrem)} 로 넘긴다. 같은 member 를 ZADD 와 ZREM
    양쪽에 넣으면 ZADD 가 이긴다.
    """
    if not items:
        raise ValueError("fenced_write needs at least one key")
    ops: dict[str, ZsetOps] = dict(zsets or {})
    if zadd or zrem:
        if zset is None:
            raise ValueError("zadd/zrem need a zset key")
        ops[zset] = (zadd or {}, zrem)
    keys = [lock_key, *items.keys(), *ops.keys()]
    args: list = [token, "" if ex is None else str(ex), len(items), *items.values(), len(ops)]
    for adds, rems in ops.values():
        adds = dict(adds)
        rems = [m for m in rems if m not in adds]
        args.append(len(adds))
        for member, score in adds.items():
            args += [member, score]
        args += [len(rems), *rems]
    async with store_errors():
        written = await redis.eval(_FENCED_WRITE_LUA, len(keys), *keys, *args)
    return bool(written)
