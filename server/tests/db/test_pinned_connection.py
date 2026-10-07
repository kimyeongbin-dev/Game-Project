"""
Redis 연결 주소 고정 (M4-1 — 검토 #3 높음 2 수정)

Redis 가 꺼진 동안 이름 조회가 수 초 걸리고 기본 스레드 풀을 채워, 복구 뒤에도 앱 풀 재접속이 늦었다(짧은 재시작이면
복구 뒤 2~3 s). 연결은 장부의 주소로 하고 조회는 따로 도는 스레드에서 한다.
"""

import asyncio
import threading
import time

from redis.asyncio import ConnectionPool, Redis

from app.core.config import settings
from app.db import redis as redis_module
from app.db.redis import AddressBook, PinnedConnection, address_book


def answer(*addresses):
    return [(None, None, None, "", (a, 6379)) for a in addresses]


def test_book_keeps_known_addresses_when_lookup_fails_and_rotates_on_failure():
    calls = []

    def resolve(name, port, **kw):
        calls.append(name)
        if len(calls) == 2:
            raise OSError("Name or service not known")      # 꺼진 동안의 NXDOMAIN
        return answer("10.0.0.5", "10.0.0.6")

    book = AddressBook("redis", 6379, resolve=resolve)
    assert book.wait(1.0) and book.current() == "10.0.0.5"
    book._looked.clear()
    book.failed()                                          # 접속 실패 → 다음 주소, 다시 조회(실패)
    book._looked.wait(1.0)
    assert book.current() == "10.0.0.6"                    # 조회가 실패해도 아는 주소 유지


def test_ip_hosts_are_not_pinned():
    assert address_book("127.0.0.1", 6379) is None
    assert address_book("redis", 6379) is address_book("redis", 6379)   # 프로세스에 하나


def test_connection_uses_the_book_address():
    book = address_book("pinned.example", 6379)
    book._addresses, book._index = ["10.9.9.9"], 0
    conn = PinnedConnection(host="pinned.example", port=6379)
    assert conn._connection_arguments()["host"] == "10.9.9.9"


async def test_reconnect_is_not_queued_behind_a_saturated_default_executor(redis_client):
    """기본 스레드 풀이 막혀 있어도(다른 재접속의 느린 조회) 끊긴 앱 풀 연결이 주소로 즉시 다시 붙는다 — 이름으로 접속하면
    getaddrinfo 가 그 풀에서 줄을 선다"""
    pool = ConnectionPool.from_url(settings.redis_url, connection_class=PinnedConnection,
                                   socket_connect_timeout=5, decode_responses=True)
    client = Redis(connection_pool=pool)
    assert await client.ping()                              # 주소를 익힌다
    redis_module._prime_address(settings.redis_url)
    await pool.disconnect()                                 # 재시작 흉내 — 풀의 연결이 전부 끊겼다
    loop = asyncio.get_running_loop()
    gate = threading.Event()
    blockers = [loop.run_in_executor(None, gate.wait, 5) for _ in range(64)]   # 기본 풀 포화
    try:
        started = time.monotonic()
        assert await asyncio.wait_for(client.ping(), 2.0)
        assert time.monotonic() - started < 1.0
    finally:
        gate.set()
        await asyncio.gather(*blockers)
        await client.aclose()
        await pool.aclose()


async def test_app_pool_is_pinned(redis_client):
    """앱 풀·리미터 클라이언트가 고정 주소 연결을 쓴다(배선)"""
    assert redis_module._pool.connection_class is PinnedConnection
    assert redis_module._limiter_client.connection_pool.connection_class is PinnedConnection
    assert redis_module.new_pubsub_client("x").connection_pool.connection_class is PinnedConnection
