"""
Database Configuration
PostgreSQL 연결 설정 및 세션 관리
"""

import logging
from typing import Optional
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import declarative_base

from app.core.config import settings

logger = logging.getLogger(__name__)

# 환경변수는 app/core/config.py 에서만 읽는다 (단일 진입점).
# 이 이름들은 기존 import 호환을 위해 유지한다.
DATABASE_URL = settings.database_url
DB_ENABLED = settings.db_enabled

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


# 스키마 생성 직렬화 키 — 워커 여럿이 빈 DB 에 동시에 create_all 하면 한쪽이 유일키 충돌로 실패해 DB 없이 뜬다
# (M3 7단계 다중 워커 실측). 값 자체는 의미 없는 상수다
SCHEMA_LOCK_KEY = 7_200_001


async def create_schema(conn) -> None:
    """트랜잭션 범위 advisory lock 을 잡고 create_all — 다른 워커는 기다렸다가 이미 있는 테이블을 건너뛴다"""
    await conn.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": SCHEMA_LOCK_KEY})
    await conn.run_sync(Base.metadata.create_all)


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
            await create_schema(conn)
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
