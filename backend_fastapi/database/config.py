"""
Database Configuration
PostgreSQL 연결 설정 및 세션 관리
"""

import os
import logging
from typing import Optional
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import declarative_base

logger = logging.getLogger(__name__)

# 환경 변수에서 DB URL 가져오기 (기본값: 로컬 PostgreSQL)
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+asyncpg://postgres:8755@localhost:5432/quoridor_db"
)

# DB 활성화 여부 (환경 변수로 비활성화 가능)
DB_ENABLED = os.getenv("DB_ENABLED", "true").lower() == "true"

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
            echo=False,  # 개발 시 True로 설정하면 SQL 쿼리 로깅
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
        logger.info("Database connection established successfully")
    except Exception as e:
        _db_available = False
        logger.warning(f"Database connection failed: {e}")
        logger.info("Server will run in memory-only mode (game data will not persist)")


async def close_db():
    """데이터베이스 연결 종료"""
    global engine
    if engine is not None:
        await engine.dispose()
        engine = None
