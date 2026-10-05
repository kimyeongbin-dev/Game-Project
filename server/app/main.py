"""
게임모아 백엔드 — FastAPI 엔트리포인트.

배선 순서와 의존 관계가 로컬·CI·배포에서 동일해야 하므로, 모든 구성은
여기 한 곳에서 명시적으로 이루어진다. 설정값은 app/core/config.py 가 유일한
환경변수 진입점이다.
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.ranking import router as ranking_router
from app.api.users import router as users_router
from app.ws.maze_handler import router as maze_ws_router
from app.ws.runtime import realtime
from app.core.config import settings
from app.db import close_db, init_db, is_db_available
from app.db.redis import close_redis, init_redis, is_redis_available, redis_health
from app.middleware.rate_limiter import (
    RateLimitExceeded,
    RateLimitMiddleware,
    limiter,
    rate_limit_exceeded_handler,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """애플리케이션 생명주기.

    기동 순서: DB -> Redis -> 실시간(버스 -> 스위퍼 -> 큐 티커 -> 종료 신호 훅)
    종료 순서: 역순 — 실시간 종료(끊김 처리 대기 -> 서버 유예 소급 -> 정지)는 Redis 를 닫기 전이다

    DB 와 Redis 는 모두 graceful degradation 이다 — 연결 실패로 기동이
    막히지 않는다. 대신 어떤 기능이 비활성인지 로그로 남긴다. Redis 가 없으면
    실시간 구성요소를 띄우지 않고 WS 접속은 1013 으로 닫힌다 (app/ws/runtime.py).
    """
    logger.info(
        "Starting server (environment=%s, testing=%s)",
        settings.environment,
        settings.testing,
    )

    await init_db()
    await init_redis()
    await realtime.start()

    logger.info(
        "Startup complete — db=%s redis=%s rate_limit=%s",
        "up" if is_db_available() else "down",
        "up" if is_redis_available() else "down",
        "on" if limiter.enabled else "off",
    )
    logger.info("Realtime %s", "on" if realtime.started else "off")

    yield

    await realtime.stop()
    await close_redis()
    await close_db()
    logger.info("Shutdown complete")


app = FastAPI(
    title="게임모아 API",
    description="통합 미니게임 플랫폼 백엔드 — 인증, 랭킹, 실시간 멀티플레이",
    version="0.1.0",
    lifespan=lifespan,
)

# ---------------------------------------------------------------------------
# 레이트 리미팅
#
# slowapi 는 `app.state.limiter` 를 규약으로 참조한다. 예외 핸들러와
# 미들웨어를 함께 등록해야 실제로 429 가 반환된다.
# 카운터 저장소는 Redis (settings.redis_limiter_url) — 워커가 여러 개여도
# 제한이 정확하다. §2.2
# ---------------------------------------------------------------------------
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, rate_limit_exceeded_handler)
app.add_middleware(RateLimitMiddleware)

# ---------------------------------------------------------------------------
# CORS
# TODO: 프로덕션에서는 허용 오리진을 명시한다 (현재 개발 편의로 전체 허용)
# ---------------------------------------------------------------------------
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
async def root():
    """API 상태 확인."""
    return {"status": "ok", "message": "게임모아 API is running"}


@app.get("/health")
async def health_check():
    """헬스 체크.

    의존 서비스 상태를 함께 보고한다. 컨테이너 HEALTHCHECK 와 배포 플랫폼의
    준비성 검사가 이 응답을 쓴다.

    DB/Redis 가 down 이어도 200 을 반환한다 — graceful degradation 설계상
    서버 자체는 정상이기 때문이다. 의존 서비스 장애는 `dependencies` 로 구분한다.
    """
    return {
        "status": "healthy",
        "environment": settings.environment,
        "dependencies": {
            "database": {"status": "ok" if is_db_available() else "unavailable"},
            "redis": await redis_health(),
        },
        "rate_limit": {
            "enabled": limiter.enabled,
            "per_minute": settings.rate_limit_per_minute,
        },
        # 이 워커의 실시간 구성요소 (M3 7단계) — 요청이 닿은 워커 하나의 값이다
        "realtime": realtime.health(),
    }


# ---------------------------------------------------------------------------
# 라우터
#
# maze WS(`/api/v1/ws/maze`, docs/api/games/maze.md §12) — M3 7단계
# ---------------------------------------------------------------------------
app.include_router(users_router)
app.include_router(ranking_router)
app.include_router(maze_ws_router)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)
