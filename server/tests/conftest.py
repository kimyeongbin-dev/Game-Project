"""
Test Configuration
pytest fixtures and configurations
"""

import os
import pytest
import pytest_asyncio
from typing import AsyncGenerator


from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker

from app.core.config import settings
from app.db import redis_keys
from app.db.config import Base
from app.db.redis import close_redis, get_redis, init_redis
from app.db.repository import GameSessionRepository, UserRepository, RankingRepository


# 테스트용 PostgreSQL 데이터베이스 (환경변수에서 읽음)
TEST_DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+asyncpg://postgres:postgres@localhost:5432/gamemoa_test"
)


@pytest_asyncio.fixture(scope="function")
async def async_engine():
    """비동기 테스트 엔진 (PostgreSQL)"""
    engine = create_async_engine(
        TEST_DATABASE_URL,
        echo=False,
    )

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    yield engine

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)

    await engine.dispose()


@pytest_asyncio.fixture(scope="function")
async def async_session(async_engine) -> AsyncGenerator[AsyncSession, None]:
    """비동기 테스트 세션"""
    async_session_factory = async_sessionmaker(
        async_engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autoflush=False
    )

    async with async_session_factory() as session:
        yield session


@pytest_asyncio.fixture(scope="function")
async def repository(async_session) -> GameSessionRepository:
    """테스트용 게임 세션 리포지토리"""
    return GameSessionRepository(async_session)


@pytest_asyncio.fixture(scope="function")
async def user_repository(async_session) -> UserRepository:
    """테스트용 유저 리포지토리"""
    return UserRepository(async_session)


@pytest_asyncio.fixture(scope="function")
async def ranking_repository(async_session) -> RankingRepository:
    """테스트용 랭킹 리포지토리"""
    return RankingRepository(async_session)


# ----- Redis (논리 DB 1) -----

async def _purge_state_keys(client) -> None:
    """멀티플레이 상태 키만 지운다. FLUSHDB 는 같은 DB 의 리미터 카운터까지 지운다"""
    for prefix in redis_keys.PREFIXES:
        async for key in client.scan_iter(match=f"{prefix}*", count=500):
            await client.delete(key)


@pytest_asyncio.fixture(scope="function")
async def redis_client():
    """앱 Redis 연결 계층을 테스트 DB 로 초기화한다 (app.db.redis 전역 상태 사용)"""
    if not settings.redis_enabled:
        pytest.skip("REDIS_ENABLED=false")
    # 앱 상태 DB 0 을 지우는 사고를 막는다 — docker-compose server-test 가 /1 을 준다
    assert settings.redis_url.rstrip("/").endswith("/1"), (
        f"tests must use Redis logical DB 1, got {settings.redis_url}"
    )

    await init_redis()
    client = get_redis()
    assert client is not None, "Redis connection failed (is the redis service up?)"
    await _purge_state_keys(client)
    yield client
    await _purge_state_keys(client)
    await close_redis()
