"""
Redis 장애 구간 기록 — 시계 면제의 전역 입력 (maze.md §8, M3 6단계 판단 8)

장애 중에는 행동이 실패한다. 그 시간은 플레이어 탓이 아니므로 두 시계에서 뺀다. 구간은 스위퍼가
관측해 `store:outages` 에 적고(app/services/sweeper.py), 시계를 정산하는 쪽이 읽는다.

여러 워커가 같은 장애를 조금씩 다르게 적어도 무해하다 — 읽는 쪽이 합집합(merge)으로 쓴다.
"""

from redis.asyncio import Redis

from app.db import redis_keys as keys
from app.db.redis_lock import store_errors
from app.services.maze_clock import Interval, merge


def _member(start: int, end: int) -> str:
    return f"{start}-{end}"


def _parse(member: str) -> Interval:
    start, _, end = member.partition("-")
    return int(start), int(end)


async def read(redis: Redis, since_ms: int) -> list[Interval]:
    """since_ms 이후에 끝난 장애 구간 (합집합)"""
    async with store_errors():
        members = await redis.zrangebyscore(keys.store_outages(), since_ms, "+inf")
    return merge(_parse(m) for m in members)


async def record(redis: Redis, start_ms: int, end_ms: int, *, retention_ms: int) -> None:
    """장애 구간 하나를 적고, 보존 기간이 지난 구간을 지운다"""
    async with store_errors():
        async with redis.pipeline(transaction=True) as pipe:
            pipe.zadd(keys.store_outages(), {_member(start_ms, end_ms): end_ms})
            pipe.zremrangebyscore(keys.store_outages(), "-inf", f"({end_ms - retention_ms}")
            await pipe.execute()
