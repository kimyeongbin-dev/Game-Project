"""
Rate Limiter Middleware
API 호출 제한 설정
"""

import os
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

# 환경 변수에서 Rate Limit 설정 로드
RATE_LIMIT_PER_MINUTE = os.getenv("RATE_LIMIT_PER_MINUTE", "60")

# Limiter 인스턴스 생성
limiter = Limiter(
    key_func=get_remote_address,
    default_limits=[f"{RATE_LIMIT_PER_MINUTE}/minute"],
    storage_uri="memory://",  # 메모리 기반 (프로덕션에서는 Redis 권장)
)


def get_rate_limit_per_minute() -> str:
    """분당 Rate Limit 반환"""
    return f"{RATE_LIMIT_PER_MINUTE}/minute"


def get_rate_limit_per_second() -> str:
    """초당 Rate Limit 반환"""
    per_second = max(1, int(RATE_LIMIT_PER_MINUTE) // 60)
    return f"{per_second}/second"


async def rate_limit_exceeded_handler(request: Request, exc: RateLimitExceeded) -> JSONResponse:
    """Rate Limit 초과 시 커스텀 응답"""
    return JSONResponse(
        status_code=429,
        content={
            "success": False,
            "error": "rate_limit_exceeded",
            "message": "요청이 너무 많습니다. 잠시 후 다시 시도해주세요.",
            "detail": str(exc.detail),
            "retry_after": getattr(exc, "retry_after", 60)
        }
    )


class RateLimitMiddleware(SlowAPIMiddleware):
    """Rate Limit 미들웨어"""
    pass
