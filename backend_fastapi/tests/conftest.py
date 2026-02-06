"""
Test Configuration
pytest fixtures and configurations
"""

import pytest
import asyncio
import sys
from pathlib import Path
from typing import AsyncGenerator

# 프로젝트 경로 설정
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))
sys.path.insert(0, str(project_root.parent))

from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.pool import StaticPool

from database.config import Base
from database.repository import GameSessionRepository


# 테스트용 인메모리 SQLite 데이터베이스
TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"


@pytest.fixture(scope="session")
def event_loop():
    """세션 범위 이벤트 루프"""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest.fixture(scope="function")
async def async_engine():
    """비동기 테스트 엔진"""
    engine = create_async_engine(
        TEST_DATABASE_URL,
        echo=False,
        poolclass=StaticPool,
    )

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    yield engine

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)

    await engine.dispose()


@pytest.fixture(scope="function")
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


@pytest.fixture(scope="function")
async def repository(async_session) -> GameSessionRepository:
    """테스트용 리포지토리"""
    return GameSessionRepository(async_session)


@pytest.fixture
def sample_game_state():
    """샘플 게임 상태"""
    return {
        "game_id": "test-game-123",
        "status": "in_progress",
        "game_mode": "vs_ai",
        "current_turn": 1,
        "turn_count": 0,
        "players": {
            "player1": {
                "name": "Player 1",
                "position": {"row": 8, "col": 4},
                "walls_remaining": 10,
                "goal_row": 0
            },
            "player2": {
                "name": "AI",
                "position": {"row": 0, "col": 4},
                "walls_remaining": 10,
                "goal_row": 8
            }
        },
        "walls": [],
        "winner": None,
        "created_at": "2024-01-01T00:00:00Z",
        "updated_at": "2024-01-01T00:00:00Z"
    }
