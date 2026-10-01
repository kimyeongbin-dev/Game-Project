"""
멀티플레이 서비스 테스트 픽스처 — 실제 Redis(논리 DB 1) + 테스트 PostgreSQL
"""

import uuid

import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.db.models import User
from app.services.maze_game import MazeGameService


@pytest_asyncio.fixture
async def session_factory(async_engine) -> async_sessionmaker:
    return async_sessionmaker(async_engine, expire_on_commit=False, autoflush=False)


@pytest_asyncio.fixture
async def games(redis_client, session_factory) -> MazeGameService:
    """테스트 DB 에 기록하는 게임 서비스"""
    return MazeGameService(lambda: session_factory)


@pytest_asyncio.fixture
async def games_no_db(redis_client) -> MazeGameService:
    """DB 가 없는 상태의 게임 서비스 (graceful degradation)"""
    return MazeGameService(lambda: None)


@pytest_asyncio.fixture
async def make_users(session_factory):
    """users 행 N개를 만들고 id 목록을 돌려준다 (game_participants.user_id FK 용)"""
    async def make(n: int) -> list[int]:
        async with session_factory() as session:
            users = [
                User(
                    nickname=f"u{uuid.uuid4().hex[:12]}",
                    password_hash="x",
                    session_token=uuid.uuid4().hex,
                )
                for _ in range(n)
            ]
            session.add_all(users)
            await session.commit()
            return [u.id for u in users]

    return make
