"""
Redis 연결 관리.

PLATFORM_ARCHITECTURE.md §2.2 — Redis 8 은 매치메이킹 큐, 실시간 방 상태,
턴 타이머, Pub/Sub 브로드캐스팅을 전담한다.

PostgreSQL 과 동일한 graceful degradation 원칙을 따른다:
연결에 실패해도 서버는 기동하고, Redis 를 필요로 하는 기능만 비활성된다.
단 PostgreSQL 과 달리 **멀티플레이는 Redis 없이는 성립하지 않는다** —
워커 간 상태 공유가 불가능하기 때문이다. 따라서 솔로/단일 워커 개발은
계속 가능하지만, 멀티플레이 기능은 `is_redis_available()` 로 가드해야 한다.
"""

import asyncio
import ipaddress
import logging
import socket
import threading
from typing import Callable, Optional
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from redis.asyncio import ConnectionPool, Redis
from redis.asyncio.retry import Retry
from redis.backoff import NoBackoff
from redis.exceptions import ConnectionError

from app.core.config import settings

logger = logging.getLogger(__name__)

_pool: Optional[ConnectionPool] = None
_client: Optional[Redis] = None
# 레이트 리미터 논리 DB(redis_limiter_db) — WS 접속 카운터(M3 7단계). 앱 상태와 같은 DB 에 두지 않는다
_limiter_client: Optional[Redis] = None
_available = False


def is_redis_available() -> bool:
    """Redis 사용 가능 여부.

    Redis 를 필요로 하는 코드는 반드시 이 함수로 먼저 확인한다.
    """
    return _available


def get_limiter_redis() -> Optional[Redis]:
    """리미터 DB 클라이언트. Redis 가 없으면 None"""
    return _limiter_client if _available else None


def get_redis() -> Optional[Redis]:
    """Redis 클라이언트 반환. 사용 불가 시 None.

    None 을 그대로 쓰면 AttributeError 가 나므로 호출부에서 분기해야 한다.
    """
    return _client if _available else None


def _retry() -> Retry:
    """끊긴 풀 연결에 한 번, 새 연결로 즉시 다시 — redis-py 기본은 0회다

    Redis 가 재시작되거나 연결이 끊기면(`CLIENT KILL`, 네트워크 단절) 풀에 남은 연결이 전부 죽는다. 재시도가 없으면 그
    연결을 다음에 쓰는 명령이 하나씩 실패한다 — 상태 쓰기는 server_busy 로 클라이언트가 다시 보내지만, **발행·전달 읽기는
    조용히 사라져** 화면이 멈춘다(M3 7단계 다중 워커 실측). 재시도는 **ConnectionError 에만** 돈다 — TimeoutError(느린
    Redis)에 돌면 이미 실행된 명령을 다시 보낸다(독립 검토 #2 Q5).
    남는 위험: 연결이 응답 도중 끊기면(ConnectionError) 실행된 명령이 한 번 더 실행될 수 있다. 펜싱 쓰기는 같은 값이라 무해하고,
    게임 락은 "이미 내 토큰이면 획득"으로 판정하며(redis_lock), 세션 키는 GET 뒤 SET 이다. 매칭 Lua(ZPOPMIN)와 PUBLISH(같은
    version 의 중복 통지 — 클라이언트가 version 으로 거른다)만 남는다 — 연결이 응답 도중 끊기는 순간에만이라 수용한다.
    """
    return Retry(NoBackoff(), 1, supported_errors=(ConnectionError,))


async def init_redis() -> None:
    """Redis 연결 풀 생성 및 헬스 확인 (실패 시 graceful degradation)."""
    global _pool, _client, _limiter_client, _available

    if not settings.redis_enabled:
        logger.info("Redis disabled by configuration (REDIS_ENABLED=false)")
        _available = False
        return

    try:
        _pool = ConnectionPool.from_url(
            settings.redis_url,
            retry=_retry(),
            max_connections=settings.redis_max_connections,
            socket_timeout=settings.redis_socket_timeout,
            socket_connect_timeout=settings.redis_socket_connect_timeout,
            health_check_interval=30,
            decode_responses=True,
        )
        _client = Redis(connection_pool=_pool)
        await _client.ping()
        _limiter_client = Redis.from_url(
            settings.redis_limiter_url,
            retry=_retry(),
            max_connections=settings.redis_max_connections,
            socket_timeout=settings.redis_socket_timeout,
            socket_connect_timeout=settings.redis_socket_connect_timeout,
            decode_responses=True,
        )
        _available = True
        logger.info("Redis connection established successfully")
    except Exception as exc:
        _available = False
        logger.warning("Redis connection failed: %s", exc)
        logger.info(
            "Server will run without Redis — multiplayer features are unavailable "
            "(matchmaking / room state / cross-worker broadcast require Redis)"
        )
        await _dispose()


def new_pubsub_client(client_name: str) -> Redis:
    """구독 전용 클라이언트 — 앱 풀과 따로 둔다 (M3 4단계 `app/ws/bus.py`).

    구독은 연결 하나를 계속 점유하고, 끊기면 통째로 새로 만든다(실측 E5 — redis-py 는
    조용히 재연결하지 않는다). `client_name` 은 CLIENT LIST 에서 버스 연결을 찾는 표식이다.
    대기는 `get_message(timeout=…)` 가 하므로 소켓 읽기 타임아웃은 두지 않고, 죽은 TCP 는
    health check PING 이 잡는다.
    """
    return Redis.from_url(
        settings.redis_url,
        client_name=client_name,
        socket_timeout=None,
        socket_connect_timeout=settings.redis_socket_connect_timeout,
        health_check_interval=30,
        decode_responses=True,
    )


# 하트비트 연결의 타임아웃은 이 모듈이 정한다 — URL 쿼리 값이 kwargs 를 이기므로(redis-py from_url) 걷어낸다(독립 검토 #3)
_HEARTBEAT_OVERRIDDEN_QUERY = ("socket_timeout", "socket_connect_timeout", "retry_on_timeout")


def _heartbeat_redis(host: Optional[str]) -> Redis:
    parts = urlsplit(settings.redis_url)
    query = urlencode([(k, v) for k, v in parse_qsl(parts.query) if k not in _HEARTBEAT_OVERRIDDEN_QUERY])
    parts = parts._replace(query=query)
    if host is not None:  # 해석해 둔 주소로 — URL 의 이름 대신
        userinfo, _, _ = parts.netloc.rpartition("@")
        port = f":{parts.port}" if parts.port else ""
        literal = f"[{host}]" if ":" in host else host
        parts = parts._replace(netloc=(f"{userinfo}@" if userinfo else "") + literal + port)
    return Redis.from_url(
        urlunsplit(parts),
        socket_timeout=settings.store_heartbeat_timeout_sec,
        socket_connect_timeout=settings.store_heartbeat_timeout_sec,
        retry=Retry(NoBackoff(), 0),
        decode_responses=True,
    )


Resolver = Callable[..., list]


class HeartbeatConnection:
    """전역 하트비트 전용 연결 — 앱 풀과 따로 둔다 (`app/services/sweeper.py` `_alive_loop`)

    하트비트는 복구 즉시 다시 성공해야 장애 끝이 실제 복구에 붙는다(M3 7단계 다중 워커 실측 S5). 그래서

    - **짧은 타임아웃, 클라이언트 재시도 없음.** 루프가 주기마다 다시 한다. 재시도가 있으면 시도 하나가 타임아웃 × 2 를 묶는다
    - **해석한 주소로 직접 접속, 이름 조회는 따로 도는 daemon 스레드.** Redis 가 꺼진 동안 이름 조회 하나가 수 초 걸리고(Docker 내장
      DNS 실측 3.3 s) 연결 타임아웃이 끝나도 조회 스레드는 계속 돈다. 워커의 모든 재접속이 asyncio 기본 스레드 풀을 그렇게 채워,
      복구 뒤 하트비트 연결의 조회가 그 뒤에 줄을 섰다(복구 뒤 1.4 s 동안 두 워커 모두 하트비트 0건 — ≈2.3 s 재시작이 4.3 s
      장애로, 실측 X7). 실패하면 다음 주소로 넘기고 다시 조회한다(주소가 바뀌었을 수 있다). 결과가 올 때까지 아는 주소로 계속
      시도하고, **아는 주소가 없으면 그 주기는 건너뛴다** — 호스트명으로 되돌아가면 기본 스레드 풀의 조회로 돌아간다
    - IP 고정은 **평문 `redis://` 에 이름이 있을 때만.** TLS(`rediss://`)는 인증서 호스트명 검증·SNI 가 이름을 필요로 하고,
      unix 소켓은 조회가 없다 — 그때는 URL 그대로(독립 검토 #3)
    - 조회 스레드는 daemon 이다 — 장애 중 종료(SIGTERM)가 걸린 조회를 기다리지 않는다
    """

    def __init__(self, resolve: Resolver = socket.getaddrinfo):
        parts = urlsplit(settings.redis_url)
        self._name, self._port = parts.hostname, parts.port or 6379
        self._pin = parts.scheme == "redis" and self._name is not None and not _is_ip(self._name)
        self._resolve = resolve
        self._lookup: Optional[asyncio.Future] = None
        self._addresses: list[str] = []
        self._index = 0
        self._client: Optional[Redis] = None
        self._closing: set[asyncio.Task] = set()

    @property
    def address(self) -> Optional[str]:
        return self._addresses[self._index] if self._addresses else None

    @property
    def pinned(self) -> bool:
        return self._pin

    async def client(self) -> Optional[Redis]:
        """이번 주기에 쓸 클라이언트. None 이면 쓸 주소가 아직 없다 — 조회를 걸어 두고 이번 주기는 건너뛴다"""
        if not self._pin:
            if self._client is None:
                self._client = _heartbeat_redis(None)
            return self._client
        self._adopt_lookup()
        if not self._addresses:
            self.refresh()
            return None
        if self._client is None:
            self._client = _heartbeat_redis(self._addresses[self._index])
        return self._client

    def failed(self) -> None:
        """시도가 실패했다 — 주소가 여럿이면 다음으로 넘기고(IPv6 우선·다중 주소), 다시 조회한다"""
        if self._pin and len(self._addresses) > 1:
            self._index = (self._index + 1) % len(self._addresses)
            self._drop_client()
        self.refresh()

    def refresh(self) -> None:
        """주소를 다시 조회한다(진행 중이면 그대로). 결과는 다음 `client()` 가 반영한다"""
        if not self._pin or (self._lookup is not None and not self._lookup.done()):
            return
        loop = asyncio.get_running_loop()
        future = loop.create_future()
        name, port, resolve = self._name, self._port, self._resolve

        def work() -> None:
            try:
                result, error = resolve(name, port, type=socket.SOCK_STREAM), None
            except BaseException as exc:  # 조회 실패(NXDOMAIN 등)는 결과로 넘긴다
                result, error = None, exc
            try:
                loop.call_soon_threadsafe(_settle, future, result, error)
            except RuntimeError:  # 루프가 이미 닫혔다(종료 중)
                pass

        threading.Thread(target=work, name="store-heartbeat-dns", daemon=True).start()
        self._lookup = future

    def _adopt_lookup(self) -> None:
        if self._lookup is None or not self._lookup.done():
            return
        lookup, self._lookup = self._lookup, None
        if lookup.cancelled() or lookup.exception() is not None:
            return  # 조회 실패(Redis 가 꺼진 동안의 NXDOMAIN 등) — 아는 주소를 유지한다
        addresses = list(dict.fromkeys(info[4][0] for info in lookup.result()))
        if not addresses or addresses == self._addresses:
            return
        current = self.address
        self._addresses = addresses
        if current in addresses:
            self._index = addresses.index(current)
        else:
            self._index = 0
            self._drop_client()

    def _drop_client(self) -> None:
        client, self._client = self._client, None
        if client is not None:
            task = asyncio.ensure_future(_close_client(client))
            self._closing.add(task)
            task.add_done_callback(self._closing.discard)

    async def aclose(self) -> None:
        self._drop_client()
        if self._closing:
            await asyncio.gather(*self._closing, return_exceptions=True)
        if self._lookup is not None:
            self._lookup.cancel()


def _settle(future: asyncio.Future, result, error) -> None:
    if future.done():
        return
    if error is not None:
        future.set_exception(error)
    else:
        future.set_result(result)


def _is_ip(host: str) -> bool:
    try:
        ipaddress.ip_address(host)
        return True
    except ValueError:
        return False


async def _close_client(client: Redis) -> None:
    try:
        await client.aclose()
    except Exception as exc:
        logger.debug("Store heartbeat client close failed: %s", exc)


async def close_redis() -> None:
    """Redis 연결 종료."""
    global _available
    _available = False
    await _dispose()
    logger.info("Redis connections closed")


async def _dispose() -> None:
    global _pool, _client, _limiter_client
    if _limiter_client is not None:
        try:
            await _limiter_client.aclose()
        except Exception as exc:
            logger.debug("Redis limiter client close failed: %s", exc)
        _limiter_client = None
    if _client is not None:
        try:
            await _client.aclose()
        except Exception as exc:  # 종료 경로에서 예외로 기동/종료를 막지 않는다
            logger.debug("Redis client close failed: %s", exc)
        _client = None
    if _pool is not None:
        try:
            await _pool.aclose()
        except Exception as exc:
            logger.debug("Redis pool close failed: %s", exc)
        _pool = None


async def redis_health() -> dict:
    """헬스 엔드포인트용 Redis 상태."""
    if not settings.redis_enabled:
        return {"status": "disabled"}
    if not _available or _client is None:
        return {"status": "unavailable"}
    try:
        pong = await _client.ping()
        return {"status": "ok" if pong else "unavailable"}
    except Exception as exc:
        logger.warning("Redis health check failed: %s", exc)
        return {"status": "unavailable", "error": str(exc)}
