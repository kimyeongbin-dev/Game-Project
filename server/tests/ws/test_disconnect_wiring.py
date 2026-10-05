"""
끊김 배선 — 소유 워커 검사, 원래 시각 재시도(검토 H4), 크로스 워커 4000(판단 4), 토큰 마스킹 (M3 7단계 B2)

실제 Redis(논리 DB 1), DB 없음. 워커 2개는 한 프로세스 안의 (연결 맵, 버스) 쌍 둘이다 — 실제 프로세스는 C(S8).
"""

import asyncio
import logging
from types import SimpleNamespace

import pytest
import pytest_asyncio

from app.core import redaction
from app.services.identity import Identity
from app.services.matchmaking import Matchmaking
from app.services.maze_game import GAME, GameBusy, MazeGameService, SeatPlayer
from app.services.rooms import Rooms
from app.ws.bus import EventBus
from app.ws.connection_manager import ConnectionManager
from app.ws.delivery import Delivery
from app.ws.maze_handler import MazeSocketHandler, Session
from app.ws.runtime import Realtime
from tests.ws.conftest import MockWebSocket
from tests.ws.test_bus import eventually
from tests.ws.test_runtime import FakeMono, FakePart


@pytest.fixture
def games(redis_client, fake_clock) -> MazeGameService:
    return MazeGameService(lambda: None, clock=fake_clock)


async def start(games, users=(1, 2)):
    return await games.create_game(
        mode="duel", is_ranked=False, players=[SeatPlayer(i + 1, u, f"n{u}") for i, u in enumerate(users)])


# ----- 서비스: 소유 워커·원래 시각 -----

async def test_old_worker_disconnect_is_ignored_after_move(games, fake_clock):
    state = await start(games)
    await games.mark_connected(state.game_id, 2, owner="wA:old")
    await games.mark_connected(state.game_id, 2, owner="wA:new")  # 같은 워커로 다시 붙었다 — 연결이 다르다(검토 R1)
    assert await games.mark_disconnected(state.game_id, 2, owner="wA:old") is None
    assert (await games.load_clocks(state.game_id)).seat(2).connected
    await games.mark_connected(state.game_id, 2, owner="wB:x")    # 다른 워커로
    assert await games.mark_disconnected(state.game_id, 2, owner="wA:new") is None
    gone = await games.mark_disconnected(state.game_id, 2, owner="wB:x")
    assert gone is not None and gone.disconnected_at_ms == fake_clock.ms


async def test_disconnect_at_original_time_is_clamped(games, fake_clock):
    state = await start(games)
    t0 = fake_clock.ms
    fake_clock.advance(4_000)
    gone = await games.redo_disconnect(state.game_id, 2, owner="w1", at_ms=t0 + 1_000)
    assert gone.disconnected_at_ms == t0 + 1_000                      # 늦게 기록해도 원래 시각
    state2 = await start(games, (3, 4))
    early = await games.redo_disconnect(state2.game_id, 4, owner="w1", at_ms=t0 - 60_000)
    assert early.disconnected_at_ms == fake_clock.ms                 # 시작(정산된 가장 늦은 시각) 전으로 되감지 않는다


# ----- 런타임: 재시도 (H4) -----

class FlakyGames:
    """처음 n 번은 끊김 기록이 GameBusy — 나머지는 진짜 서비스"""

    def __init__(self, real: MazeGameService, failures: int):
        self.real, self.failures = real, failures

    async def _maybe_fail(self):
        if self.failures > 0:
            self.failures -= 1
            raise GameBusy("lock contended")

    async def mark_disconnected(self, *args, **kwargs):
        await self._maybe_fail()
        return await self.real.mark_disconnected(*args, **kwargs)

    async def redo_disconnect(self, *args, **kwargs):
        await self._maybe_fail()
        return await self.real.redo_disconnect(*args, **kwargs)

    def __getattr__(self, name):
        return getattr(self.real, name)


async def test_failed_disconnect_is_retried_with_original_time(games, fake_clock):
    state = await start(games)
    flaky = FlakyGames(games, failures=2)
    handler = MazeSocketHandler(manager=ConnectionManager(), games=flaky, worker_id="w1")
    rt = Realtime(handler, games=flaky, bus=FakePart("bus", SimpleNamespace(calls=[])),
                  sweeper=FakePart("s", SimpleNamespace(calls=[])), ticker=FakePart("t", SimpleNamespace(calls=[])),
                  clock=fake_clock, worker_id="w1", monotonic_ms=FakeMono(fake_clock))
    t_disconnect = fake_clock.ms
    session = Session(Identity(2, "n2", 1000), SimpleNamespace(replaced=False, user_id=2, conn_id="w1:c2"))
    await rt._record_disconnect(session, 1006)
    assert len(rt.pending) == 1 and (await games.load_clocks(state.game_id)).seat(2).connected

    fake_clock.advance(3_000)
    assert await rt.retry_pending() == 0 and len(rt.pending) == 1     # 두 번째도 실패
    fake_clock.advance(3_000)
    assert await rt.retry_pending() == 1 and rt.pending == []
    seat = (await games.load_clocks(state.game_id)).seat(2)
    assert seat.disconnected_at_ms == t_disconnect                   # 6 s 늦게 기록됐지만 끊긴 시각 그대로
    assert rt.recent.since(t_disconnect)                             # 서버 유예 후보로도 남는다
    if rt._retry_task:
        rt._retry_task.cancel()


async def test_retry_gives_up_after_limit(games, fake_clock, monkeypatch):
    from app.core.config import settings
    monkeypatch.setattr(settings, "disconnect_retry_max_sec", 5)
    state = await start(games)
    flaky = FlakyGames(games, failures=100)
    handler = MazeSocketHandler(manager=ConnectionManager(), games=flaky, worker_id="w1")
    rt = Realtime(handler, games=flaky, bus=FakePart("b", SimpleNamespace(calls=[])),
                  sweeper=FakePart("s", SimpleNamespace(calls=[])), ticker=FakePart("t", SimpleNamespace(calls=[])),
                  clock=fake_clock, worker_id="w1", monotonic_ms=FakeMono(fake_clock))
    await rt._record_disconnect(Session(Identity(2, "n2", 1000), SimpleNamespace(replaced=False, user_id=2, conn_id="w1:c2")), 1006)
    fake_clock.advance(6_000)
    await rt.retry_pending()
    assert rt.pending == []
    if rt._retry_task:
        rt._retry_task.cancel()
    assert state.game_id


# ----- 크로스 워커 4000 (판단 4) -----

@pytest_asyncio.fixture
async def two_workers(redis_client, fake_clock):
    games = MazeGameService(lambda: None, clock=fake_clock)
    rooms, mm = Rooms(games={GAME: games}), Matchmaking(games={GAME: games})
    pairs, buses = [], []
    for wid in ("wA", "wB"):
        manager = ConnectionManager()
        delivery = Delivery(games, rooms, mm, clock=fake_clock)
        handler = MazeSocketHandler(manager=manager, games=games, rooms=rooms, matches=mm,
                                    delivery=delivery, worker_id=wid)
        bus = EventBus(manager, delivery)
        await bus.start()
        pairs.append(handler)
        buses.append(bus)
    yield games, pairs
    for bus in buses:
        await bus.stop()


async def attach(handler: MazeSocketHandler, user_id: int) -> tuple[MockWebSocket, Session]:
    ws = MockWebSocket()
    conn = await handler.manager.connect(ws, user_id, f"n{user_id}")
    conn.conn_id = f"{handler.worker_id}:{conn.conn_id}"
    session = Session(Identity(user_id, f"n{user_id}", 1000), conn)
    await handler._claim_session(session)
    return ws, session


async def test_cross_worker_replacement(two_workers):
    games, (a, b) = two_workers
    state = await start(games)
    opponent_ws, _ = await attach(b, 1)
    old_ws, old = await attach(a, 2)
    await games.mark_connected(state.game_id, 2, owner=old.conn.conn_id)

    new_ws, new = await attach(b, 2)                                  # 같은 계정이 다른 워커로
    await games.mark_connected(state.game_id, 2, owner=new.conn.conn_id)
    await eventually(lambda: old_ws.closed)
    assert old_ws.close_code == 4000 and old.conn.replaced
    assert a.manager.get_connection(2) is None and b.manager.get_connection(2) is new.conn
    assert not new_ws.closed                                          # 새 연결은 그대로

    # 옛 워커의 늦은 끊김 처리 — 핸들러는 replaced 라 부르지 않고, 불러도 서비스가 owner 로 무시한다
    assert await games.mark_disconnected(state.game_id, 2, owner=old.conn.conn_id) is None
    await asyncio.sleep(0.1)
    assert not [m for m in opponent_ws.sent_messages if m["type"] == "player_left"]
    assert (await games.load_clocks(state.game_id)).seat(2).connected


async def test_same_worker_reclaim_does_not_kick_itself(two_workers):
    games, (a, _) = two_workers
    ws1, s1 = await attach(a, 7)
    ws2, s2 = await attach(a, 7)                                      # 같은 워커 — 연결 맵이 옛 것을 닫는다
    assert ws1.close_code == 4000
    await asyncio.sleep(0.1)
    assert not ws2.closed and a.manager.get_connection(7) is s2.conn


# ----- 토큰 마스킹 -----

def test_token_is_redacted_from_logs(caplog):
    caplog.set_level(logging.INFO)
    redaction.install()                      # 기동 때처럼 로깅 설정(여기선 caplog 핸들러) 뒤에
    token = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxIn0.c2lnbmF0dXJl"
    logging.getLogger("uvicorn.error").info('%s - "WebSocket %s" [accepted]', "1.2.3.4",
                                            f"/api/v1/ws/maze?token={token}")
    logging.getLogger("app.ws").warning("rejected ?token=%s&x=1", token)
    assert token not in caplog.text
    assert caplog.text.count("token=***") == 2
