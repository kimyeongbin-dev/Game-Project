"""
WebSocket Test Fixtures
WebSocket 테스트용 fixture 정의
"""

import pytest
import pytest_asyncio
from unittest.mock import AsyncMock, MagicMock
from dataclasses import dataclass
from datetime import datetime

import sys
from pathlib import Path

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))


# ==============================================
# Mock 클래스 정의
# ==============================================

@dataclass
class MockUser:
    """테스트용 Mock 유저"""
    id: int
    nickname: str
    score: float = 10.0
    wins: int = 5
    losses: int = 2


class MockWebSocket:
    """테스트용 Mock WebSocket"""

    def __init__(self):
        self.accepted = False
        self.closed = False
        self.close_code = None
        self.close_reason = None
        self.sent_messages = []
        self.receive_queue = []

    async def accept(self):
        self.accepted = True

    async def close(self, code=1000, reason=""):
        self.closed = True
        self.close_code = code
        self.close_reason = reason

    async def send_json(self, data: dict):
        self.sent_messages.append(data)

    async def receive_json(self):
        if self.receive_queue:
            return self.receive_queue.pop(0)
        raise Exception("No message in queue")

    def add_receive_message(self, message: dict):
        self.receive_queue.append(message)


# ==============================================
# Fixtures
# ==============================================

@pytest.fixture
def mock_websocket():
    """Mock WebSocket 인스턴스"""
    return MockWebSocket()


@pytest.fixture
def mock_user():
    """테스트용 유저"""
    return MockUser(id=1, nickname="TestUser", score=10.0)


@pytest.fixture
def mock_user2():
    """두 번째 테스트용 유저"""
    return MockUser(id=2, nickname="TestUser2", score=15.0)


@pytest_asyncio.fixture
async def connection_manager():
    """ConnectionManager 인스턴스"""
    from websocket.connection_manager import ConnectionManager
    return ConnectionManager()


@pytest_asyncio.fixture
async def matchmaking_queue():
    """MatchmakingQueue 인스턴스 (started)"""
    from websocket.matchmaking import MatchmakingQueue
    queue = MatchmakingQueue()
    await queue.start()
    yield queue
    await queue.stop()


@pytest_asyncio.fixture
async def matchmaking_queue_stopped():
    """MatchmakingQueue 인스턴스 (not started)"""
    from websocket.matchmaking import MatchmakingQueue
    return MatchmakingQueue()


@pytest.fixture
def room_manager():
    """RoomManager 인스턴스"""
    from websocket.room_manager import RoomManager
    return RoomManager()
