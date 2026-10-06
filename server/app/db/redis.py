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

import logging
from typing import Optional

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
