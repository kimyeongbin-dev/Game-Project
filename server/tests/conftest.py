"""
Test Configuration
pytest fixtures and configurations
"""

import os
import pytest
import pytest_asyncio
from typing import AsyncGenerator


from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker

from app.core.config import TEST_PUBSUB_NAMESPACE, settings
from app.db import redis_keys
from app.db.config import Base
from app.db.redis import close_redis, get_redis, init_redis
from app.db.repository import GameSessionRepository, UserRepository, RankingRepository
from app.games.maze.core.layouts import CORNER_SLOTS, LAYOUTS, Layout


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
    # Pub/Sub 채널은 논리 DB 로 격리되지 않는다 — 네임스페이스가 따로 막는다
    assert settings.pubsub_namespace == TEST_PUBSUB_NAMESPACE, (
        f"tests must use PUBSUB_NAMESPACE={TEST_PUBSUB_NAMESPACE}, got {settings.pubsub_namespace}"
    )

    await init_redis()
    client = get_redis()
    assert client is not None, "Redis connection failed (is the redis service up?)"
    await _purge_state_keys(client)
    yield client
    await _purge_state_keys(client)
    await close_redis()


# ----- 시계 (M3 6단계) -----

class FakeClock:
    """app.core.time.Clock 의 테스트 구현 — 만료를 실제 sleep 으로 기다리지 않는다"""

    def __init__(self, start_ms: int = 1_759_000_000_000):
        self.ms = start_ms

    async def now_ms(self) -> int:
        return self.ms

    def advance(self, ms: int) -> int:
        self.ms += ms
        return self.ms

    def set(self, ms: int) -> int:
        self.ms = ms
        return self.ms


@pytest.fixture
def fake_clock() -> FakeClock:
    return FakeClock()


# ----- 좌석 수 파라미터화 -----

# 테스트 전용 4인 배치. 인당 벽 수는 설계서에서 미정(§11 "—")이라 임의값이다
QUAD_LAYOUT = Layout(slots=CORNER_SLOTS, seats=4, walls_per_seat=5, shuffle=True)


@pytest.fixture(
    params=[("duel", 2), ("trio", 3), ("quad", 4)],
    ids=["duel-2", "trio-3", "quad-4"],
)
def seat_mode(request, monkeypatch) -> tuple[str, int]:
    """(mode, 좌석 수). quad 는 배치 테이블에 행을 **추가하는 것만으로** 주입한다.

    이 픽스처로 도는 테스트가 quad 에서 통과한다는 것이 "인원이 4명이 되면 무엇을
    고쳐야 하는가?" → 테이블 행 추가뿐 이라는 판정이다 (M3 1단계 엔진, 3단계 서비스).
    """
    mode, seats = request.param
    if mode == "quad":
        monkeypatch.setitem(LAYOUTS, "quad", QUAD_LAYOUT)
    return mode, seats
