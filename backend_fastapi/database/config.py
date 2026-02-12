"""
Database Configuration
PostgreSQL 연결 설정 및 세션 관리
"""

import os
import logging
from pathlib import Path
from typing import Optional
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import declarative_base

# .env 파일 로드 (python-dotenv 사용)
try:
    from dotenv import load_dotenv
    # backend_fastapi 디렉토리의 .env 파일 로드
    env_path = Path(__file__).parent.parent / ".env"
    load_dotenv(env_path)
except ImportError:
    pass  # python-dotenv가 없으면 환경 변수만 사용

logger = logging.getLogger(__name__)

# =============================================
# 환경 변수에서 설정 로드
# =============================================

# 앱 환경 (development, staging, production)
APP_ENV = os.getenv("APP_ENV", "development")
IS_PRODUCTION = APP_ENV == "production"

# 개별 DB 설정
DB_HOST = os.getenv("DB_HOST", "localhost")
DB_PORT = os.getenv("DB_PORT", "5432")
DB_NAME = os.getenv("DB_NAME", "quoridor_db")
DB_USER = os.getenv("DB_USER", "postgres")
DB_PASSWORD = os.getenv("DB_PASSWORD", "")

# DATABASE_URL이 설정되어 있으면 우선 사용, 없으면 개별 설정으로 구성
DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    if DB_PASSWORD:
        DATABASE_URL = f"postgresql+asyncpg://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"
    else:
        # 비밀번호가 없는 경우 경고
        logger.warning("DB_PASSWORD not set. Please configure your .env file.")
        DATABASE_URL = f"postgresql+asyncpg://{DB_USER}@{DB_HOST}:{DB_PORT}/{DB_NAME}"

# DB 활성화 여부 (환경 변수로 비활성화 가능)
DB_ENABLED = os.getenv("DB_ENABLED", "true").lower() == "true"

# SQL 쿼리 로깅 (개발 환경에서만)
LOG_SQL_QUERIES = os.getenv("LOG_SQL_QUERIES", "false").lower() == "true"

# =============================================
# 데이터베이스 엔진 설정
# =============================================

# DB 연결 상태
_db_available = False

# Base 클래스 (모델 정의에 사용)
Base = declarative_base()

# 엔진 및 세션 팩토리 (초기화는 나중에)
engine = None
async_session_factory = None


def _create_engine():
    """엔진 생성"""
    global engine, async_session_factory
    if engine is None:
        engine = create_async_engine(
            DATABASE_URL,
            echo=LOG_SQL_QUERIES,  # 환경 변수로 SQL 쿼리 로깅 제어
            pool_pre_ping=True,  # 연결 유효성 검사
            pool_size=5,
            max_overflow=10
        )
        async_session_factory = async_sessionmaker(
            engine,
            class_=AsyncSession,
            expire_on_commit=False,
            autoflush=False
        )
    return engine


def is_db_available() -> bool:
    """DB 사용 가능 여부 반환"""
    return _db_available


def get_session_factory():
    """세션 팩토리 반환 (import 시점 문제 해결용)"""
    return async_session_factory


def get_app_env() -> str:
    """현재 앱 환경 반환"""
    return APP_ENV


def is_production() -> bool:
    """프로덕션 환경인지 확인"""
    return IS_PRODUCTION


async def get_db_session() -> Optional[AsyncSession]:
    """의존성 주입용 DB 세션 제공"""
    if not _db_available or async_session_factory is None:
        yield None
        return

    async with async_session_factory() as session:
        try:
            yield session
        finally:
            await session.close()


async def init_db():
    """데이터베이스 테이블 생성 (연결 실패 시 graceful degradation)"""
    global _db_available

    if not DB_ENABLED:
        logger.info("Database disabled by configuration (DB_ENABLED=false)")
        _db_available = False
        return

    try:
        _create_engine()
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        _db_available = True
        logger.info(f"Database connection established successfully (ENV: {APP_ENV})")
    except Exception as e:
        _db_available = False
        # 프로덕션에서는 에러 상세 정보 숨김
        if IS_PRODUCTION:
            logger.warning("Database connection failed. Server will run in memory-only mode.")
        else:
            logger.warning(f"Database connection failed: {e}")
        logger.info("Server will run in memory-only mode (game data will not persist)")


async def close_db():
    """데이터베이스 연결 종료"""
    global engine
    if engine is not None:
        await engine.dispose()
        engine = None
