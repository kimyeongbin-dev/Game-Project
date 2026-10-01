"""
Redis 락·펜싱 쓰기 — 실제 Redis(논리 DB 1)로 검증한다

maze.md §8: 행동·스위퍼 만료·항복이 모두 같은 게임별 락으로 직렬화된다.
"""

import asyncio

import pytest

from app.db.redis_lock import LockTimeout, StoreUnavailable, fenced_set, redis_lock, require_redis

KEY = "game:test-lock:lock"
TARGET = "game:test-lock:state"


async def test_acquire_sets_token_and_release_deletes(redis_client):
    async with redis_lock(redis_client, KEY) as token:
        assert await redis_client.get(KEY) == token
    assert await redis_client.get(KEY) is None


async def test_lock_has_ttl(redis_client):
    async with redis_lock(redis_client, KEY, ttl_ms=5000):
        assert 0 < await redis_client.pttl(KEY) <= 5000


async def test_mutual_exclusion_under_contention(redis_client):
    """락 없이는 갱신이 유실되는 read-sleep-write 를 10개가 동시에 해도 정확하다"""
    await redis_client.set(TARGET, 0)

    async def increment():
        async with redis_lock(redis_client, KEY, wait_ms=5000):
            value = int(await redis_client.get(TARGET))
            await asyncio.sleep(0.005)
            await redis_client.set(TARGET, value + 1)

    await asyncio.gather(*(increment() for _ in range(10)))
    assert int(await redis_client.get(TARGET)) == 10


async def test_wait_limit_raises_lock_timeout(redis_client):
    async with redis_lock(redis_client, KEY):
        with pytest.raises(LockTimeout):
            async with redis_lock(redis_client, KEY, wait_ms=50):
                pass


async def test_expired_owner_does_not_release_new_owner(redis_client):
    """TTL 로 풀린 옛 소유자가 나갈 때 새 소유자의 락을 지우지 않는다"""
    old_holding = asyncio.Event()
    release_old = asyncio.Event()

    async def old_owner():
        async with redis_lock(redis_client, KEY, ttl_ms=50):
            old_holding.set()
            await release_old.wait()

    task = asyncio.create_task(old_owner())
    await old_holding.wait()
    await asyncio.sleep(0.08)  # 옛 락 만료

    async with redis_lock(redis_client, KEY, wait_ms=0) as new_token:
        release_old.set()
        await task
        assert await redis_client.get(KEY) == new_token


async def test_fenced_set_writes_while_holding(redis_client):
    async with redis_lock(redis_client, KEY) as token:
        assert await fenced_set(redis_client, KEY, token, TARGET, "v1", ex=30) is True
    assert await redis_client.get(TARGET) == "v1"
    assert 0 < await redis_client.ttl(TARGET) <= 30


async def test_fenced_set_rejects_after_lock_lost(redis_client):
    """락 TTL 을 넘긴 행동은 다음 소유자의 결과를 덮어쓰지 못한다"""
    async with redis_lock(redis_client, KEY, ttl_ms=50) as stale_token:
        await asyncio.sleep(0.08)
        async with redis_lock(redis_client, KEY, wait_ms=0) as fresh_token:
            assert await fenced_set(redis_client, KEY, fresh_token, TARGET, "fresh") is True
            assert await fenced_set(redis_client, KEY, stale_token, TARGET, "stale") is False
    assert await redis_client.get(TARGET) == "fresh"


async def test_require_redis_raises_when_unavailable(monkeypatch):
    import app.db.redis as redis_module

    monkeypatch.setattr(redis_module, "_available", False)
    with pytest.raises(StoreUnavailable):
        require_redis()
