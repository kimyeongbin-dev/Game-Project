"""
WS 핸들러 테스트용 실서버 — 스레드 안의 uvicorn + `websockets` 클라이언트 (M3 7단계)

TestClient 는 수신에 타임아웃이 없어 기대한 메시지가 안 오면 테스트가 멈추고, accept 전후 close 동작이 실제 서버와
다르다. 그래서 실제 uvicorn 을 스레드에서 띄운다. 서버의 Redis 클라이언트(app.db.redis 전역)는 서버 스레드의
이벤트 루프에 묶이므로, 이 서버를 쓰는 테스트는 `redis_client` 픽스처를 쓰지 않고 `raw_redis()` 로 따로 연결한다.
"""

import asyncio
import json
import threading
import time
from contextlib import asynccontextmanager
from typing import Optional

import uvicorn
from fastapi import FastAPI
from redis.asyncio import Redis
from websockets.asyncio.client import connect
from websockets.exceptions import ConnectionClosed

from app.core.config import settings
from app.db import redis_keys
from app.db.redis import close_redis, init_redis
from app.core.worker import WORKER_ID
from app.services.matchmaking import Matchmaking
from app.services.maze_game import GAME, MazeGameService
from app.services.rooms import Rooms
from app.ws.bus import EventBus
from app.ws.connection_manager import ConnectionManager
from app.ws.delivery import Delivery
from app.ws.maze_handler import PATH, MazeSocketHandler, build_router
from tests.conftest import mint_token

RECV_SEC = 3.0


def raw_redis() -> Redis:
    return Redis.from_url(settings.redis_url, decode_responses=True)


async def purge(client: Redis) -> None:
    for prefix in redis_keys.PREFIXES:
        async for key in client.scan_iter(match=f"{prefix}*", count=500):
            await client.delete(key)


def build_handler(identity, *, worker_id: str = WORKER_ID, **overrides) -> MazeSocketHandler:
    """DB 없는 서비스로 조립한 핸들러 — 앱 싱글턴은 다른 테스트가 켠 DB 상태를 물려받을 수 있다"""
    games = MazeGameService(lambda: None)
    rooms = Rooms(games={GAME: games})
    matches = Matchmaking(games={GAME: games})
    return MazeSocketHandler(
        manager=ConnectionManager(), games=games, rooms=rooms, matches=matches,
        delivery=Delivery(games, rooms, matches, worker_id=worker_id),
        identity=identity, worker_id=worker_id, **overrides,
    )


def build_app(handler: MazeSocketHandler) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app):
        await init_redis()
        bus = EventBus(handler.manager, handler.delivery)
        await bus.start()
        app.state.bus = bus
        yield
        await bus.stop()
        await close_redis()

    app = FastAPI(lifespan=lifespan)
    app.include_router(build_router(handler))
    return app


class LiveServer:
    def __init__(self, app: FastAPI):
        self.config = uvicorn.Config(app, host="127.0.0.1", port=0, log_level="warning",
                                     lifespan="on", ws="websockets", ws_ping_interval=None)
        self.server = uvicorn.Server(self.config)
        self.thread = threading.Thread(target=self.server.run, daemon=True)
        self.port: Optional[int] = None

    def start(self) -> "LiveServer":
        self.thread.start()
        deadline = time.monotonic() + 10
        while not self.server.started:
            if time.monotonic() > deadline or not self.thread.is_alive():
                raise RuntimeError("live server did not start")
            time.sleep(0.02)
        self.port = self.server.servers[0].sockets[0].getsockname()[1]
        return self

    def stop(self) -> None:
        self.server.should_exit = True
        self.thread.join(timeout=10)

    def url(self, token: Optional[str]) -> str:
        base = f"ws://127.0.0.1:{self.port}{PATH}"
        return base if token is None else f"{base}?token={token}"


class Client:
    """한 유저의 소켓. 받은 메시지를 전부 남긴다(누설 검사용)"""

    def __init__(self, server: LiveServer, user_id: int):
        self.server, self.user_id = server, user_id
        self.ws = None
        self.received: list[dict] = []
        self._pending: list[dict] = []   # 읽었지만 아직 아무도 가져가지 않은 메시지
        self._seq = 0

    async def open(self, token: Optional[str] = None, *, expect_connected: bool = True) -> "Client":
        self.ws = await connect(self.server.url(token if token is not None else mint_token(self.user_id)))
        if expect_connected:
            self.connected = await self.recv("connected")
        return self

    async def send(self, type_: str, payload: Optional[dict] = None, *, raw: Optional[str] = None) -> int:
        self._seq += 1
        frame = raw if raw is not None else json.dumps(
            {"type": type_, "seq": self._seq, **({"payload": payload} if payload is not None else {})})
        await self.ws.send(frame)
        return self._seq

    async def next(self, timeout: float = RECV_SEC) -> dict:
        message = json.loads(await asyncio.wait_for(self.ws.recv(), timeout))
        self.received.append(message)
        return message

    async def take(self, predicate, timeout: float = RECV_SEC) -> dict:
        """조건에 맞는 첫 메시지 — 먼저 보관함에서, 없으면 더 읽는다. 맞지 않는 것은 보관한다"""
        for i, message in enumerate(self._pending):
            if predicate(message):
                return self._pending.pop(i)
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout
        while True:
            message = await self.next(max(0.01, deadline - loop.time()))
            if predicate(message):
                return message
            self._pending.append(message)

    async def recv(self, type_: str, timeout: float = RECV_SEC, **match) -> dict:
        """type_ 인(그리고 payload 가 match 를 만족하는) 다음 메시지"""
        return await self.take(lambda m: m["type"] == type_ and all(
            m.get("payload", {}).get(k) == v for k, v in match.items()), timeout)

    async def reply(self, seq: int, timeout: float = RECV_SEC) -> dict:
        """ack_seq 가 seq 인 응답"""
        return await self.take(lambda m: m.get("ack_seq") == seq, timeout)

    async def quiet(self, seconds: float = 0.3) -> list[dict]:
        """seconds 동안 오는 것을 모은다"""
        got, self._pending = self._pending, []
        try:
            while True:
                got.append(await self.next(seconds))
        except (asyncio.TimeoutError, TimeoutError):
            return got

    async def closed_code(self, timeout: float = RECV_SEC) -> int:
        try:
            while True:
                self.received.append(json.loads(await asyncio.wait_for(self.ws.recv(), timeout)))
        except ConnectionClosed as exc:
            return exc.rcvd.code if exc.rcvd is not None else 1006

    async def close(self) -> None:
        if self.ws is not None:
            await self.ws.close()
