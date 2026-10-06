"""
전역 하트비트 전용 루프 (M3 7단계 다중 워커 실측 S5)

스위퍼 회차(1 s)에 묶인 하트비트는 장애 양 끝을 회차 단위로 어긋나게 찍었다 — ≈1.9 s 재시작이 3 s 장애로 기록되고,
10.3 s 정지가 12.8 s 면제됐다. 전용 루프는 짧은 주기·스크립트 안 Redis TIME 으로 그 오차를 줄인다.
"""

import asyncio

from app.core.config import settings
from app.core.time import redis_clock
from app.db import redis_keys as keys
from app.services import outages
from app.services.sweeper import DeadlineSweeper
from tests.conftest import FakeClock


async def no_sources():
    return []


async def server_ms(redis) -> int:
    seconds, micros = await redis.time()
    return int(seconds) * 1000 + int(micros) // 1000


async def test_beat_stamps_the_server_time_inside_the_script(redis_client):
    """미리 읽은 시각이 아니라 실행 순간의 Redis TIME — 장애 끝이 복구 순간에 붙는다"""
    now = await server_ms(redis_client)
    await redis_client.set(keys.store_alive(), now - 5_000)
    outage = await outages.beat(redis_client, min_ms=3_000, retention_ms=60_000)
    after = await server_ms(redis_client)
    assert outage is not None and outage[0] == now - 5_000
    assert now <= outage[1] <= after
    assert int(await redis_client.get(keys.store_alive())) == outage[1]


async def test_alive_loop_keeps_the_heartbeat_fresh_between_sweeper_ticks(redis_client, monkeypatch):
    """하트비트 공백이 전용 주기 단위 — 회차 주기(1 s)보다 훨씬 작다. 장애 시작 추정 오차가 이 값이다"""
    monkeypatch.setattr(settings, "sweeper_interval_ms", 10_000)   # 회차가 하트비트를 대신 갱신하지 못하게
    sweeper = DeadlineSweeper(clock=redis_clock, in_progress_source=no_sources)
    await sweeper.start()
    try:
        await asyncio.sleep(0.3)
        stale = []
        for _ in range(8):
            await asyncio.sleep(0.13)
            stale.append(await server_ms(redis_client) - int(await redis_client.get(keys.store_alive())))
    finally:
        await sweeper.stop()
    assert max(stale) <= 2 * settings.store_heartbeat_interval_ms + 100, stale


async def test_alive_loop_closes_an_outage_right_after_recovery(redis_client):
    """멈춰 있던 하트비트(장애) — 전용 루프가 주기 안에 공백을 닫는다. 기록의 끝 ≈ 복구 시각"""
    sweeper = DeadlineSweeper(clock=redis_clock, in_progress_source=no_sources)
    recovered = await server_ms(redis_client)
    await redis_client.set(keys.store_alive(), recovered - 4_000)   # 4 s 동안 아무도 쓰지 못했다
    await sweeper.start()
    try:
        await asyncio.sleep(2 * settings.store_heartbeat_interval_ms / 1000 + 0.1)
    finally:
        await sweeper.stop()
    recorded = await outages.read(redis_client, recovered - 10_000)
    assert len(recorded) == 1 and recorded[0][0] == recovered - 4_000
    assert recorded[0][1] - recovered <= 2 * settings.store_heartbeat_interval_ms + 100


async def test_injected_clock_does_not_start_the_server_time_heartbeat(redis_client):
    """가짜 시각을 쓰는 테스트에 Redis TIME 하트비트가 섞이면 공백 판정이 엉킨다"""
    sweeper = DeadlineSweeper(clock=FakeClock(), in_progress_source=no_sources)
    await sweeper.start()
    try:
        assert sweeper._alive_task is None
    finally:
        await sweeper.stop()


def test_heartbeat_client_fails_fast_without_client_retry():
    """복구 뒤 첫 성공이 늦지 않게 — 시도 하나가 묶는 시간 = 타임아웃 하나(재시도 없음). 루프가 주기마다 다시 한다"""
    from app.db.redis import new_heartbeat_client
    client = new_heartbeat_client()
    kwargs = client.connection_pool.connection_kwargs
    retry = client.get_retry()
    assert retry is None or retry.get_retries() == 0
    assert kwargs["socket_connect_timeout"] <= 0.5 and kwargs["socket_timeout"] <= 0.5
