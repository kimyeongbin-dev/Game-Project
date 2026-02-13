"""
Game Project Backend - FastAPI
Phase 1: 기본 인프라 및 API 설정
"""

import os
import sys
import logging
from pathlib import Path
from contextlib import asynccontextmanager

# 프로젝트 루트를 path에 추가 (games 패키지 접근용)
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.httpsredirect import HTTPSRedirectMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.openapi.utils import get_openapi
from slowapi.errors import RateLimitExceeded

from routers.quoridor import router as quoridor_router
from routers.users import router as users_router
from routers.ranking import router as ranking_router
from routers.ws_game import router as ws_game_router
from database import init_db, close_db, is_db_available
from database.config import get_app_env, is_production
from database.memory_store import memory_store
from scheduler import setup_scheduler, shutdown_scheduler
from middleware.rate_limiter import limiter, rate_limit_exceeded_handler
from websocket import matchmaking_queue

# ==============================================
# 로깅 설정
# ==============================================

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
APP_ENV = get_app_env()

# ==============================================
# 로깅 설정 (모드별)
# ==============================================
# LOG_LEVEL 옵션:
#   DEBUG   - 모든 로그 (SQL 쿼리 포함, 디버깅용)
#   INFO    - 핵심 기능만 (개발용, 기본값)
#   WARNING - 경고/에러만 (배포용)
# ==============================================

if APP_ENV == "development":
    log_format = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
else:
    log_format = "%(asctime)s - %(levelname)s - %(message)s"

logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format=log_format
)

# 로그 레벨에 따른 세부 설정
if LOG_LEVEL == "DEBUG":
    # 디버깅 모드: SQL 쿼리 포함 모든 로그
    logging.getLogger("sqlalchemy.engine").setLevel(logging.INFO)
    logging.getLogger("sqlalchemy.pool").setLevel(logging.INFO)
    logging.getLogger("uvicorn.access").setLevel(logging.INFO)
else:
    # 개발/배포 모드: 핵심 로그만 (SQL 완전 숨김)
    logging.getLogger("sqlalchemy").setLevel(logging.ERROR)
    logging.getLogger("sqlalchemy.engine").setLevel(logging.ERROR)
    logging.getLogger("sqlalchemy.pool").setLevel(logging.ERROR)
    logging.getLogger("sqlalchemy.engine.Engine").setLevel(logging.ERROR)
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("uvicorn.error").setLevel(logging.WARNING)
    logging.getLogger("websockets").setLevel(logging.WARNING)
    logging.getLogger("apscheduler").setLevel(logging.WARNING)

logger = logging.getLogger(__name__)

# ==============================================
# CORS 설정
# ==============================================

CORS_ORIGINS = os.getenv("CORS_ORIGINS", "*")
if CORS_ORIGINS == "*":
    cors_origins = ["*"]
else:
    cors_origins = [origin.strip() for origin in CORS_ORIGINS.split(",")]

# ==============================================
# 애플리케이션 라이프사이클
# ==============================================


@asynccontextmanager
async def lifespan(app: FastAPI):
    """애플리케이션 생명주기 관리"""
    # 시작: 데이터베이스 초기화
    logger.info(f"Starting application (ENV: {APP_ENV})")
    logger.info("Initializing database...")
    await init_db()
    logger.info("Database initialized successfully")

    # 메모리 모드일 경우 테스트 유저 초기화
    if not is_db_available():
        logger.info("DB not available, initializing memory store with test users...")
        memory_store.initialize_test_users()

    # 스케줄러 시작
    logger.info("Starting scheduler...")
    setup_scheduler()
    logger.info("Scheduler started")

    # 매칭 큐 시작
    logger.info("Starting matchmaking queue...")
    await matchmaking_queue.start()
    logger.info("Matchmaking queue started")

    yield

    # 종료: 매칭 큐 정리
    logger.info("Stopping matchmaking queue...")
    await matchmaking_queue.stop()
    logger.info("Matchmaking queue stopped")

    # 종료: 스케줄러 정리
    logger.info("Shutting down scheduler...")
    shutdown_scheduler()
    logger.info("Scheduler stopped")

    # 종료: 데이터베이스 연결 정리
    logger.info("Closing database connections...")
    await close_db()
    logger.info("Database connections closed")


# ==============================================
# FastAPI 애플리케이션
# ==============================================

app = FastAPI(
    title="Game Project API",
    description="게임 허브 백엔드 API - 유저 관리, 게임 정보, 점수 기록",
    version="0.1.0",
    lifespan=lifespan,
    # 프로덕션에서는 docs 비활성화 옵션
    docs_url="/docs" if not is_production() else None,
    redoc_url="/redoc" if not is_production() else None,
)

# Rate Limiter 설정
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, rate_limit_exceeded_handler)

# HTTPS 리다이렉트 (프로덕션에서 SSL 활성화 시)
SSL_ENABLED = os.getenv("SSL_ENABLED", "false").lower() == "true"
if is_production() and SSL_ENABLED:
    app.add_middleware(HTTPSRedirectMiddleware)

# CORS 설정
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ==============================================
# OpenAPI 보안 스키마 (Swagger Authorize 버튼)
# ==============================================

def custom_openapi():
    if app.openapi_schema:
        return app.openapi_schema
    openapi_schema = get_openapi(
        title="Game Project API",
        version="0.1.0",
        description="게임 허브 백엔드 API - 유저 관리, 게임 정보, 점수 기록",
        routes=app.routes,
    )
    # Bearer 토큰 인증 스키마 추가
    openapi_schema["components"]["securitySchemes"] = {
        "BearerAuth": {
            "type": "http",
            "scheme": "bearer",
            "bearerFormat": "Token",
            "description": "로그인 후 받은 session_token을 입력하세요"
        }
    }
    # 모든 엔드포인트에 보안 적용 (선택적)
    openapi_schema["security"] = [{"BearerAuth": []}]
    app.openapi_schema = openapi_schema
    return app.openapi_schema

app.openapi = custom_openapi

# ==============================================
# 전역 예외 핸들러
# ==============================================


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """
    전역 예외 핸들러
    - 개발 환경: 상세 에러 메시지 반환
    - 프로덕션 환경: 일반적인 에러 메시지만 반환
    """
    logger.error(f"Unhandled exception: {exc}", exc_info=True)

    if is_production():
        # 프로덕션: 민감 정보 숨김
        return JSONResponse(
            status_code=500,
            content={
                "success": False,
                "error": "internal_server_error",
                "message": "서버 내부 오류가 발생했습니다."
            }
        )
    else:
        # 개발: 상세 정보 제공
        return JSONResponse(
            status_code=500,
            content={
                "success": False,
                "error": "internal_server_error",
                "message": str(exc),
                "type": type(exc).__name__
            }
        )


# ==============================================
# 기본 엔드포인트
# ==============================================


@app.get("/")
@limiter.limit("30/minute")
async def root(request: Request):
    """API 상태 확인"""
    return {
        "status": "ok",
        "message": "Game Project API is running",
        "environment": APP_ENV
    }


@app.get("/health")
@limiter.limit("60/minute")
async def health_check(request: Request):
    """헬스 체크 엔드포인트"""
    return {"status": "healthy"}


# ==============================================
# 라우터 등록
# ==============================================

app.include_router(quoridor_router)
app.include_router(users_router)
app.include_router(ranking_router)
app.include_router(ws_game_router)

# 정적 파일 (테스트 페이지)
static_dir = Path(__file__).parent / "static"
if static_dir.exists():
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

# ==============================================
# 직접 실행 시
# ==============================================

if __name__ == "__main__":
    import uvicorn

    # SSL 설정 (프로덕션 환경용)
    ssl_enabled = os.getenv("SSL_ENABLED", "false").lower() == "true"
    ssl_certfile = os.getenv("SSL_CERT_FILE")
    ssl_keyfile = os.getenv("SSL_KEY_FILE")

    uvicorn_config = {
        "app": "main:app",
        "host": "0.0.0.0",
        "port": 8000,
        "reload": APP_ENV == "development",
        "log_level": LOG_LEVEL.lower(),
    }

    # HTTPS 설정
    if ssl_enabled and ssl_certfile and ssl_keyfile:
        uvicorn_config["ssl_certfile"] = ssl_certfile
        uvicorn_config["ssl_keyfile"] = ssl_keyfile
        logger.info("Starting with HTTPS enabled")

    uvicorn.run(**uvicorn_config)
