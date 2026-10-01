"""
Test Configuration
pytest fixtures and configurations
"""

import os
import pytest
import pytest_asyncio
from typing import AsyncGenerator


from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker

from app.db.config import Base
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
