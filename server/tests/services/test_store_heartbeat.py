"""
전역 하트비트 전용 루프 (M3 7단계 다중 워커 실측 S5)

스위퍼 회차(1 s)에 묶인 하트비트는 장애 양 끝을 회차 단위로 어긋나게 찍었다 — ≈1.9 s 재시작이 3 s 장애로 기록되고,
10.3 s 정지가 12.8 s 면제됐다. 전용 루프는 짧은 주기·스크립트 안 Redis TIME 으로 그 오차를 줄인다.
"""

import asyncio

import pytest

from app.core.config import settings
from app.core.time import redis_clock
from app.db import redis_keys as keys
from urllib.parse import urlsplit

from app.db.redis import HeartbeatConnection
from app.services import outages
from app.services.sweeper import DeadlineSweeper
from tests.conftest import FakeClock


async def no_sources():
    return []


async def server_ms(redis) -> int:
    seconds, micros = await redis.time()
    return int(seconds) * 1000 + int(micros) // 1000


async def test_beat_records_the_gap_ending_at_the_server_time(redis_client):
    """시각 인자 없이 Redis TIME 으로 공백을 닫는다(왕복 한 번). "미리 읽은 시각"과의 차이는 이 테스트가 판별하지 않는다 —
    두 방식 모두 TIME 도 장애 뒤에 처리되므로 결과가 같다(독립 검토 #3 낮음: 이름을 주장에 맞췄다)"""
    now = await server_ms(redis_client)
    await redis_client.set(keys.store_alive(), now - 5_000)
    outage = await outages.beat(redis_client, min_ms=3_000, retention_ms=60_000)
    after = await server_ms(redis_client)
    assert outage is not None and outage[0] == now - 5_000
    assert now <= outage[1] <= after
    assert int(await redis_client.get(keys.store_alive())) == outage[1]


FRESH_BOUND_MS = 500   # 설정값을 참조하지 않는다 — 주기를 1 s 로 되돌리면 실패해야 한다(검토 #3)


def no_ticks(monkeypatch):
    """회차(앱 풀로 하트비트를 함께 남긴다)를 끈다 — 전용 루프만 검증하게(검토 #3: 회차가 공백을 대신 닫아 통과했다)"""
    async def idle(self):
        return None
    monkeypatch.setattr(DeadlineSweeper, "tick", idle)


def spy_connections(monkeypatch) -> list:
    """전용 연결로 하트비트를 보내는지 — 루프가 앱 풀을 써도 통과하지 않게"""
    import app.services.sweeper as sweeper_module
    used = []

    class Spy(HeartbeatConnection):
        async def client(self):
            got = await super().client()
            if got is not None:
                used.append(got)
            return got

    monkeypatch.setattr(sweeper_module, "HeartbeatConnection", Spy)
    return used


async def ready(conn: HeartbeatConnection, timeout: float = 1.0):
    """첫 조회가 끝날 때까지 — 주소가 없으면 그 주기는 건너뛴다(None)"""
    deadline = asyncio.get_running_loop().time() + timeout
    while True:
        client = await conn.client()
        if client is not None:
            return client
        assert asyncio.get_running_loop().time() < deadline, "lookup did not finish"
        await asyncio.sleep(0.01)


def answer(*addresses):
    return [(None, None, None, "", (a, 6379)) for a in addresses]


async def test_alive_loop_keeps_the_heartbeat_fresh_between_sweeper_ticks(redis_client, monkeypatch):
    """하트비트 공백이 전용 주기 단위 — 회차 주기(1 s)보다 훨씬 작다. 장애 시작 추정 오차가 이 값이다"""
    no_ticks(monkeypatch)
    used = spy_connections(monkeypatch)
    sweeper = DeadlineSweeper(clock=redis_clock, in_progress_source=no_sources)
    await sweeper.start()
    try:
        await asyncio.sleep(0.4)
        stale = []
        for _ in range(8):
            await asyncio.sleep(0.13)
            stale.append(await server_ms(redis_client) - int(await redis_client.get(keys.store_alive())))
    finally:
        await sweeper.stop()
    assert used, "heartbeat did not go through the dedicated connection"
    assert max(stale) <= FRESH_BOUND_MS, stale


async def test_alive_loop_closes_an_outage_right_after_recovery(redis_client, monkeypatch):
    """멈춰 있던 하트비트(장애) — 전용 루프가 주기 안에 공백을 닫는다. 기록의 끝 ≈ 복구 시각"""
    no_ticks(monkeypatch)
    sweeper = DeadlineSweeper(clock=redis_clock, in_progress_source=no_sources)
    recovered = await server_ms(redis_client)
    await redis_client.set(keys.store_alive(), recovered - 4_000)   # 4 s 동안 아무도 쓰지 못했다
    await sweeper.start()
    try:
        await asyncio.sleep(0.6)
    finally:
        await sweeper.stop()
    recorded = await outages.read(redis_client, recovered - 10_000)
    assert len(recorded) == 1 and recorded[0][0] == recovered - 4_000
    assert recorded[0][1] - recovered <= FRESH_BOUND_MS


async def test_injected_clock_does_not_start_the_server_time_heartbeat(redis_client):
    """가짜 시각을 쓰는 테스트에 Redis TIME 하트비트가 섞이면 공백 판정이 엉킨다"""
    sweeper = DeadlineSweeper(clock=FakeClock(), in_progress_source=no_sources)
    await sweeper.start()
    try:
        assert sweeper._alive_task is None
    finally:
        await sweeper.stop()


async def test_heartbeat_attempt_to_an_unreachable_address_fails_within_one_timeout():
    """복구 뒤 첫 성공이 늦지 않게 — 시도 하나가 묶는 시간 = 타임아웃 하나(재시도 없음). 실제로 잰다(검토 #3)"""
    conn = HeartbeatConnection(resolve=lambda host, port, **kw: answer("10.255.255.1"))   # 응답 없는 주소
    try:
        client = await ready(conn)
        loop = asyncio.get_running_loop()
        started = loop.time()
        with pytest.raises(Exception):
            await outages.beat(client, min_ms=3_000, retention_ms=60_000)
        assert loop.time() - started <= 0.8
    finally:
        await conn.aclose()


async def test_heartbeat_connects_by_resolved_address_and_keeps_it_when_lookup_fails():
    """이름 조회는 따로 도는 스레드 — 연결은 그 주소로. Redis 가 꺼진 동안 조회가 실패해도 아는 주소로 계속 시도하고,
    조회가 다른 주소를 주면 바꾼다(실측 X7: 꺼진 동안 조회 하나가 3.3 s, 기본 스레드 풀 포화로 복구 뒤 1.4 s 하트비트 0건)"""
    answers = [("10.0.0.5", None), (None, OSError("Name or service not known")), ("10.0.0.6", None)]
    calls = []

    def resolve(host, port, **kw):
        calls.append(host)
        address, error = answers[min(len(calls), len(answers)) - 1]
        if error is not None:
            raise error
        return answer(address)

    conn = HeartbeatConnection(resolve=resolve)
    try:
        first = await ready(conn)
        assert first.connection_pool.connection_kwargs["host"] == "10.0.0.5"
        assert calls == [urlsplit(settings.redis_url).hostname]
        conn.failed()                                    # 실패 → 다시 조회(이번엔 실패)
        await asyncio.sleep(0.05)
        assert (await conn.client()) is first            # 아는 주소 유지
        conn.failed()                                    # 다시 조회 → 새 주소
        await asyncio.sleep(0.05)
        moved = await conn.client()
        assert moved.connection_pool.connection_kwargs["host"] == "10.0.0.6" and moved is not first
    finally:
        await conn.aclose()


async def test_heartbeat_rotates_through_every_resolved_address():
    """첫 주소만 쓰면 IPv6 가 먼저 오고 Redis 가 IPv4 에만 있을 때 영원히 실패한다 — 실패마다 다음 주소로(검토 #3)"""
    conn = HeartbeatConnection(resolve=lambda host, port, **kw: answer("::1", "127.0.0.1"))
    try:
        assert (await ready(conn)).connection_pool.connection_kwargs["host"] == "::1"
        conn.failed()
        assert (await conn.client()).connection_pool.connection_kwargs["host"] == "127.0.0.1"
        conn.failed()
        assert (await conn.client()).connection_pool.connection_kwargs["host"] == "::1"
    finally:
        await conn.aclose()


async def test_without_any_known_address_the_beat_is_skipped_not_sent_by_hostname():
    """아는 주소가 없으면 그 주기는 건너뛴다 — 호스트명으로 되돌아가면 기본 스레드 풀의 조회로 돌아간다(검토 #3)"""
    def fail(host, port, **kw):
        raise OSError("Name or service not known")

    conn = HeartbeatConnection(resolve=fail)
    try:
        for _ in range(5):
            assert await conn.client() is None
            await asyncio.sleep(0.02)
    finally:
        await conn.aclose()


@pytest.mark.parametrize("url, host", [
    ("rediss://:pw@redis.example:6380/0", "redis.example"),     # TLS — 인증서 호스트명 검증·SNI 에 이름이 필요하다
    ("redis://127.0.0.1:6379/1", "127.0.0.1"),                  # 이미 주소
])
async def test_address_pinning_only_for_plain_tcp_hostnames(monkeypatch, url, host):
    monkeypatch.setattr(settings, "redis_url", url)
    calls = []
    conn = HeartbeatConnection(resolve=lambda *a, **kw: calls.append(a) or answer("10.0.0.9"))
    try:
        assert not conn.pinned
        client = await conn.client()
        assert client.connection_pool.connection_kwargs["host"] == host and not calls
    finally:
        await conn.aclose()


async def test_unix_socket_url_is_used_as_is(monkeypatch):
    monkeypatch.setattr(settings, "redis_url", "unix:///tmp/redis.sock?db=1")
    conn = HeartbeatConnection(resolve=lambda *a, **kw: answer("10.0.0.9"))
    try:
        assert not conn.pinned
        kwargs = (await conn.client()).connection_pool.connection_kwargs
        assert kwargs["path"] == "/tmp/redis.sock" and "host" not in kwargs
    finally:
        await conn.aclose()


async def test_url_query_cannot_override_the_heartbeat_timeouts(monkeypatch):
    """redis-py 는 URL 쿼리가 kwargs 를 이긴다 — 하트비트의 0.5 s 를 무력화하지 못하게 걷어낸다(검토 #3)"""
    monkeypatch.setattr(settings, "redis_url", "redis://:pw@redis:6379/1?socket_timeout=5&socket_connect_timeout=5")
    conn = HeartbeatConnection(resolve=lambda host, port, **kw: answer("10.0.0.9"))
    try:
        kwargs = (await ready(conn)).connection_pool.connection_kwargs
        assert kwargs["socket_timeout"] <= 0.5 and kwargs["socket_connect_timeout"] <= 0.5
        assert kwargs["password"] == "pw" and kwargs["db"] == 1
        retry = (await conn.client()).get_retry()
        assert retry is None or retry.get_retries() == 0
    finally:
        await conn.aclose()


async def test_heartbeat_lookup_runs_off_the_default_executor_on_a_daemon_thread():
    """기본 스레드 풀이 막혀 있어도(다른 재접속들의 느린 조회) 하트비트의 조회는 기다리지 않는다. 조회 스레드는 daemon —
    장애 중 종료가 걸린 조회를 기다리지 않는다(검토 #3)"""
    import threading
    loop = asyncio.get_running_loop()
    gate = threading.Event()
    blockers = [loop.run_in_executor(None, gate.wait, 5) for _ in range(64)]   # 기본 풀 포화
    daemon = []

    def resolve(host, port, **kw):
        daemon.append(threading.current_thread().daemon)
        return answer("10.1.2.3")

    try:
        conn = HeartbeatConnection(resolve=resolve)
        try:
            client = await asyncio.wait_for(ready(conn), 1.0)
            assert client.connection_pool.connection_kwargs["host"] == "10.1.2.3"
            assert daemon == [True]
        finally:
            await conn.aclose()
    finally:
        gate.set()
        await asyncio.gather(*blockers)

