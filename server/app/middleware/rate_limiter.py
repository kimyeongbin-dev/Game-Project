"""
레이트 리미터 — API 호출 제한.

## 왜 Redis 를 쓰는가

slowapi 의 기본 저장소는 프로세스 메모리다. 워커나 인스턴스가 여러 개면
각자 따로 카운트하므로 실효 제한이 워커 수만큼 곱해진다 (워커 2개 = 분당 120회).
PLATFORM_ARCHITECTURE.md §2.2 의 Redis 를 카운터 저장소로 쓰면
워커·인스턴스 수와 무관하게 제한이 정확해진다.

Redis 를 쓸 수 없을 때는 메모리 저장소로 자동 강등한다 — 제한이 느슨해지지만
서버가 뜨지 않는 것보다는 낫다. 다중 워커 환경에서 이 강등이 일어났다면
경고 로그가 남는다.

## 프록시 뒤에서의 클라이언트 식별

`get_remote_address` 는 `request.client.host` 를 본다. 리버스 프록시 뒤에서는
이 값이 프록시 IP 가 되어 **모든 사용자가 하나의 제한을 공유**한다.
uvicorn 을 `--proxy-headers --forwarded-allow-ips` 와 함께 실행하면
Starlette 이 `X-Forwarded-For` 를 반영해 `request.client.host` 를 교정하므로
이 함수가 실제 클라이언트 IP 를 보게 된다. prod CMD 에 해당 옵션이 있다.
"""

import logging

from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from slowapi.util import get_remote_address
from starlette.requests import Request
from starlette.responses import JSONResponse

from app.core.config import settings

logger = logging.getLogger(__name__)


def _storage_uri() -> str:
    """리미터 카운터 저장소 URI.

    Redis 가 활성이면 전용 논리 DB 를, 아니면 메모리로 강등한다.
    """
    if settings.redis_enabled:
        return settings.redis_limiter_url
    logger.warning(
        "Rate limiter falling back to in-memory storage — limits are per-process. "
        "Do not run multiple workers in this configuration."
    )
    return "memory://"


limiter = Limiter(
    key_func=get_remote_address,
    default_limits=[f"{settings.rate_limit_per_minute}/minute"],
    storage_uri=_storage_uri(),
    # 테스트에서는 비활성이 기본이다. 리미터 자체를 검증하는 테스트는
    # limiter.enabled 를 직접 켜서 확인한다 (tests/api/test_rate_limit.py).
    enabled=settings.rate_limit_enabled and not settings.testing,
)


def get_rate_limit_per_minute() -> str:
    """분당 제한 문자열 (라우터 데코레이터용)."""
    return f"{settings.rate_limit_per_minute}/minute"


def get_rate_limit_per_second() -> str:
    """초당 제한 문자열 (라우터 데코레이터용)."""
    per_second = max(1, settings.rate_limit_per_minute // 60)
    return f"{per_second}/second"


def rate_limit_exceeded_handler(request: Request, exc: Exception) -> JSONResponse:
    """제한 초과 시 응답.

    **반드시 동기 함수여야 한다.** SlowAPIMiddleware 는 동기 컨텍스트에서
    핸들러를 호출하며, 코루틴 함수를 발견하면 조용히 slowapi 기본 핸들러로
    대체한다 (slowapi/middleware.py 의 sync_check_limits 참조).
    async def 로 두면 이 커스텀 응답이 전혀 쓰이지 않는다.

    시그니처의 `Exception` 은 Starlette 예외 핸들러 계약 때문이며,
    실제로는 RateLimitExceeded 만 전달된다.
    """
    detail = getattr(exc, "detail", str(exc))
    retry_after = getattr(exc, "retry_after", 60)
    return JSONResponse(
        status_code=429,
        content={
            "success": False,
            "error": "rate_limit_exceeded",
            "message": "요청이 너무 많습니다. 잠시 후 다시 시도해주세요.",
            "detail": str(detail),
            "retry_after": retry_after,
        },
        headers={"Retry-After": str(retry_after)},
    )


class RateLimitMiddleware(SlowAPIMiddleware):
    """전역 레이트 리미트 미들웨어 (default_limits 적용)."""


__all__ = [
    "limiter",
    "RateLimitMiddleware",
    "RateLimitExceeded",
    "rate_limit_exceeded_handler",
    "get_rate_limit_per_minute",
    "get_rate_limit_per_second",
]
