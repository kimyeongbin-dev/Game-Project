"""
Test Configuration
pytest fixtures and configurations
"""

import os
import pytest
import pytest_asyncio
import sys
from pathlib import Path
from typing import AsyncGenerator
from unittest.mock import patch, AsyncMock, MagicMock

# ==============================================
# 테스트 환경 설정
# ==============================================

# Rate limiter 비활성화 (높은 값으로 설정)
os.environ["RATE_LIMIT_PER_MINUTE"] = "10000"
os.environ["TESTING"] = "true"
os.environ["LOG_LEVEL"] = "WARNING"

# 프로젝트 경로 설정
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))
sys.path.insert(0, str(project_root.parent))

from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker

from database.config import Base
from database.repository import GameSessionRepository, UserRepository, RankingRepository


# ==============================================
# DB 연결 설정
# ==============================================

# 테스트용 PostgreSQL 데이터베이스 (환경변수에서 읽음)
TEST_DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+asyncpg://postgres:postgres@localhost:5432/quoridor_test_db"
)


def is_db_available() -> bool:
    """PostgreSQL DB 연결 가능 여부 확인"""
    try:
        import asyncpg
        import asyncio

        async def check():
            try:
                # URL에서 연결 정보 추출
                from urllib.parse import urlparse
                parsed = urlparse(TEST_DATABASE_URL.replace("+asyncpg", ""))
                conn = await asyncpg.connect(
                    user=parsed.username or "postgres",
                    password=parsed.password or "postgres",
                    database=parsed.path.lstrip("/") or "quoridor_test_db",
                    host=parsed.hostname or "localhost",
                    port=parsed.port or 5432,
                    timeout=2.0
                )
                await conn.close()
                return True
            except Exception:
                return False

        return asyncio.get_event_loop().run_until_complete(check())
    except Exception:
        return False


# DB 연결 가능 여부 확인 (테스트 시작 시 1회)
DB_AVAILABLE = is_db_available()


# ==============================================
# 마커 정의
# ==============================================

def pytest_configure(config):
    """pytest 마커 등록"""
    config.addinivalue_line(
        "markers", "requires_db: mark test as requiring PostgreSQL database"
    )


def pytest_collection_modifyitems(config, items):
    """DB 없을 때 requires_db 마커가 있는 테스트 스킵"""
    if DB_AVAILABLE:
        return

    skip_db = pytest.mark.skip(reason="PostgreSQL database not available")
    for item in items:
        if "requires_db" in item.keywords:
            item.add_marker(skip_db)


# ==============================================
# DB Fixtures (requires_db 마커 필요)
# ==============================================

@pytest_asyncio.fixture(scope="function")
async def async_engine():
    """비동기 테스트 엔진 (PostgreSQL)"""
    if not DB_AVAILABLE:
        pytest.skip("PostgreSQL database not available")

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


# ==============================================
# API 테스트용 Fixtures
# ==============================================

class MockUser:
    """테스트용 Mock 유저"""
    id = 1
    nickname = "TestPlayer"
    email = "test@test.com"
    score = 10.0
    wins = 5
    losses = 2
    best_turn_count = 15


@pytest.fixture
def mock_user():
    """테스트용 유저 객체"""
    return MockUser()


@pytest.fixture
def mock_get_current_user():
    """get_current_user 모킹 함수"""
    async def _mock(authorization=None):
        return MockUser()
    return _mock


@pytest.fixture
def client(mock_get_current_user):
    """테스트 클라이언트 - lifespan 의존성을 모두 mock"""
    from fastapi.testclient import TestClient
    from main import app

    with patch('main.init_db', new_callable=AsyncMock), \
         patch('main.close_db', new_callable=AsyncMock), \
         patch('main.is_db_available', return_value=False), \
         patch('main.setup_scheduler'), \
         patch('main.shutdown_scheduler'), \
         patch('main.matchmaking_queue') as mock_queue, \
         patch('services.quoridor_service.is_db_available', return_value=False), \
         patch('routers.quoridor.get_current_user', mock_get_current_user), \
         patch('routers.users.get_current_user', mock_get_current_user), \
         patch('routers.ranking.get_current_user', mock_get_current_user):
        # matchmaking_queue의 start/stop을 AsyncMock으로 설정
        mock_queue.start = AsyncMock()
        mock_queue.stop = AsyncMock()

        with TestClient(app) as c:
            # 테스트용 인증 헤더 추가
            c.headers["Authorization"] = "Bearer test-token"
            yield c


@pytest.fixture
def unauthenticated_client():
    """인증 없는 테스트 클라이언트"""
    from fastapi.testclient import TestClient
    from main import app

    with patch('main.init_db', new_callable=AsyncMock), \
         patch('main.close_db', new_callable=AsyncMock), \
         patch('main.is_db_available', return_value=False), \
         patch('main.setup_scheduler'), \
         patch('main.shutdown_scheduler'), \
         patch('main.matchmaking_queue') as mock_queue, \
         patch('services.quoridor_service.is_db_available', return_value=False):
        mock_queue.start = AsyncMock()
        mock_queue.stop = AsyncMock()

        with TestClient(app) as c:
            yield c


# ==============================================
# 게임 상태 Fixtures
# ==============================================

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


@pytest.fixture
def sample_wall():
    """샘플 벽 데이터"""
    return {
        "row": 4,
        "col": 4,
        "orientation": "horizontal"
    }


# ==============================================
# 서비스 테스트용 Fixtures
# ==============================================

@pytest.fixture
def quoridor_service():
    """테스트용 QuoridorService (메모리 모드)"""
    from services.quoridor_service import QuoridorService

    with patch('services.quoridor_service.is_db_available', return_value=False):
        service = QuoridorService()
        yield service
        # 테스트 후 게임 캐시 클리어
        service._games.clear()
        service._ai_instances.clear()
        service._ai_difficulties.clear()
        service._last_accessed.clear()
