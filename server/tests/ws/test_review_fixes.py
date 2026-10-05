"""
독립 검토 #1 회귀 — 연결 단위 소유(R1·R3), 활동 읽기 실패 재시도(R2), 교체 판정의 권위(R10)
(docs/research/2026-10-06-M3-7단계-독립검토-1.md). 검토자의 재현 테스트를 연결 id 소유에 맞춰 옮겼다.

실제 Redis(논리 DB 1), DB 없음. 런타임은 가짜 부품 + 가짜 시계(단조 시계도 같은 축).
"""

import asyncio
from types import SimpleNamespace

import pytest

from app.db import redis_keys as keys
from app.db.redis_lock import StoreUnavailable
from app.services import events
from app.services.identity import Identity
from app.services.maze_game import GameBusy, MazeGameService, SeatPlayer
from app.ws.bus import EventBus
from app.ws.connection_manager import ConnectionManager
from app.ws.delivery import Delivery
from app.ws.maze_handler import MazeSocketHandler, Session
from app.ws.runtime import REPLACE_SETTLE_SEC, Realtime
from tests.ws.conftest import MockWebSocket
from tests.ws.test_bus import eventually
from tests.ws.test_runtime import FakeMono, FakePart


class Flaky:
    """처음 n 번은 끊김 기록이 GameBusy"""

    def __init__(self, real, failures):
        self.real, self.failures = real, failures

    async def mark_disconnected(self, *a, **k):
        if self.failures > 0:
            self.failures -= 1
            raise GameBusy("contended")
        return await self.real.mark_disconnected(*a, **k)

    def __getattr__(self, name):
        return getattr(self.real, name)


def rt_for(games, clock, worker="w1") -> Realtime:
    handler = MazeSocketHandler(manager=ConnectionManager(), games=games, worker_id=worker)
    parts = SimpleNamespace(calls=[])
    return Realtime(handler, games=games, bus=FakePart("b", parts), sweeper=FakePart("s", parts),
                    ticker=FakePart("t", parts), clock=clock, worker_id=worker, monotonic_ms=FakeMono(clock))


def session(user_id: int, conn_id: str, *, replaced: bool = False) -> Session:
    return Session(Identity(user_id, f"n{user_id}", 1000),
                   SimpleNamespace(replaced=replaced, user_id=user_id, conn_id=conn_id))


@pytest.fixture
def real(redis_client, fake_clock) -> MazeGameService:
    return MazeGameService(lambda: None, clock=fake_clock)


async def start(games):
    return await games.create_game(mode="duel", is_ranked=False,
                                   players=[SeatPlayer(1, 1, "a"), SeatPlayer(2, 2, "b")])


async def done(rt: Realtime):
    if rt._retry_task:
        rt._retry_task.cancel()


# ----- R1: 재시도 vs 같은 워커 재접속 -----

async def test_retry_after_same_worker_reconnect_keeps_live_seat(real, fake_clock):
    state = await start(real)
    await real.mark_connected(state.game_id, 2, owner="w1:old")
    rt = rt_for(Flaky(real, 1), fake_clock)
    await rt._record_disconnect(session(2, "w1:old"), 1006)
    assert len(rt.pending) == 1
    fake_clock.advance(500)
    await real.mark_connected(state.game_id, 2, owner="w1:new")   # 같은 워커로 재접속 (E1 의 대부분)
    fake_clock.advance(1_000)
    await rt.retry_pending()
    await done(rt)
    assert rt.pending == []
    assert (await real.load_clocks(state.game_id)).seat(2).connected   # 살아 있는 연결은 그대로


async def test_retry_still_records_when_nobody_came_back(real, fake_clock):
    """대조군 — 다시 붙지 않았으면 원래 시각으로 끊김이 남는다"""
    state = await start(real)
    await real.mark_connected(state.game_id, 2, owner="w1:old")
    rt = rt_for(Flaky(real, 1), fake_clock)
    t0 = fake_clock.ms
    await rt._record_disconnect(session(2, "w1:old"), 1006)
    fake_clock.advance(1_500)
    await rt.retry_pending()
    await done(rt)
    assert (await real.load_clocks(state.game_id)).seat(2).disconnected_at_ms == t0


# ----- R2: 활동 읽기 실패 -----

async def test_activity_read_failure_is_retried(real, fake_clock, monkeypatch):
    state = await start(real)
    rt = rt_for(real, fake_clock)
    calls = {"n": 0}
    original = rt.handler._activity

    async def blip(uid):
        calls["n"] += 1
        if calls["n"] == 1:
            raise StoreUnavailable("blip")
        return await original(uid)

    monkeypatch.setattr(rt.handler, "_activity", blip)
    t0 = fake_clock.ms
    await rt._record_disconnect(session(2, "w1:c"), 1006)
    assert len(rt.pending) == 1 and rt.pending[0].game_id is None
    fake_clock.advance(2_000)
    assert await rt.retry_pending() == 1
    await done(rt)
    assert (await real.load_clocks(state.game_id)).seat(2).disconnected_at_ms == t0


# ----- R3: 밀려난 연결의 정착 확인 -----

async def test_replaced_connection_records_when_new_one_never_took_the_seat(real, fake_clock):
    """새 연결이 소유를 못 가져간 채 끝났다 — 옛 연결의 끊김이 정착 시간 뒤 원래 시각으로 남는다"""
    state = await start(real)
    await real.mark_connected(state.game_id, 2, owner="wA:old")
    rt = rt_for(real, fake_clock, worker="wA")
    t0 = fake_clock.ms
    await rt._record_disconnect(session(2, "wA:old", replaced=True), 4000)
    assert await rt.retry_pending() == 0                       # 아직 정착 전 — 기다린다
    fake_clock.advance(int(REPLACE_SETTLE_SEC * 1000) + 10)
    assert await rt.retry_pending() == 1
    await done(rt)
    seat = (await real.load_clocks(state.game_id)).seat(2)
    assert not seat.connected and seat.disconnected_at_ms == t0


async def test_replaced_connection_is_silent_when_new_one_took_the_seat(real, fake_clock):
    state = await start(real)
    await real.mark_connected(state.game_id, 2, owner="wA:old")
    rt = rt_for(real, fake_clock, worker="wA")
    await rt._record_disconnect(session(2, "wA:old", replaced=True), 4000)
    await real.mark_connected(state.game_id, 2, owner="wB:new")   # 정상 교체
    fake_clock.advance(int(REPLACE_SETTLE_SEC * 1000) + 10)
    await rt.retry_pending()
    await done(rt)
    assert (await real.load_clocks(state.game_id)).seat(2).connected


# ----- R10: 교체 판정은 Redis 의 현재 연결 id -----

async def test_late_replacement_event_does_not_close_the_newest_connection(redis_client, fake_clock):
    games = MazeGameService(lambda: None, clock=fake_clock)
    manager = ConnectionManager()
    bus = EventBus(manager, Delivery(games, None, None, clock=fake_clock))
    await bus.start()
    try:
        ws = MockWebSocket()
        conn = await manager.connect(ws, 5, "n5")
        conn.conn_id = "wA:c3"                                    # C1(wA) → C2(wB) → C3(wA) 의 C3
        await redis_client.set(keys.user_conn(5), "wA:c3")
        stale = events.session_replaced(5, "wB:c2")               # C2 때 나간 이벤트가 늦게 왔다
        await redis_client.publish(stale.channel, stale.to_json())
        await asyncio.sleep(0.2)
        assert not ws.closed and manager.get_connection(5) is conn

        await redis_client.set(keys.user_conn(5), "wB:c4")        # 진짜로 다른 워커가 가져갔다
        fresh = events.session_replaced(5, "wB:c4")
        await redis_client.publish(fresh.channel, fresh.to_json())
        await eventually(lambda: ws.closed)
        assert ws.close_code == 4000
    finally:
        await bus.stop()


# ----- R4: 처음부터 없던 좌석 -----

async def test_absent_player_starts_disconnected(redis_client, fake_clock):
    from app.services.maze_game import Presence

    games = MazeGameService(lambda: None, clock=fake_clock, presence=Presence())
    await redis_client.zadd(keys.workers(), {"wA": fake_clock.ms, "wDead": fake_clock.ms - 60_000})
    await redis_client.set(keys.user_conn(1), "wA:c1")            # 붙어 있다
    await redis_client.set(keys.user_conn(3), "wDead:c3")         # 크래시한 워커가 남긴 키 — 붙어 있지 않다
    state = await games.create_game(mode="trio", is_ranked=False,
                                    players=[SeatPlayer(1, 1, "a"), SeatPlayer(2, 2, "b"), SeatPlayer(3, 3, "c")])
    clocks = await games.load_clocks(state.game_id)
    assert clocks.seat(1).connected
    assert clocks.seat(2).disconnected_at_ms == fake_clock.ms     # 매치·방에서 준비한 뒤 끊겼다
    assert clocks.seat(3).disconnected_at_ms == fake_clock.ms
    members = await redis_client.zrange(keys.deadlines("maze_1p"), 0, -1)
    assert keys.deadline_grace(state.game_id, 2) in members       # 접속 시계가 흐른다 — 스위퍼가 기권패를 낸다


async def test_without_presence_everyone_starts_connected(real):
    """서비스 단위 테스트의 전제 — Presence 를 안 넘기면 예전처럼 전원 연결로 시작한다"""
    state = await start(real)
    clocks = await real.load_clocks(state.game_id)
    assert clocks.seat(1).connected and clocks.seat(2).connected


# ----- R5·R6·R12: 게임 경계의 전달 -----

async def test_left_spectator_gets_nothing_more(real, fake_clock):
    from app.services.matchmaking import Matchmaking
    from app.services.rooms import Rooms

    d = Delivery(real, Rooms(games={"maze_1p": real}), Matchmaking(games={"maze_1p": real}), clock=fake_clock)
    pub = []

    class Rec:
        async def publish(self, e):
            pub.append(e)

    real._publisher = Rec()
    state = await real.create_game(mode="trio", is_ranked=False,
                                   players=[SeatPlayer(1, 1, "a"), SeatPlayer(2, 2, "b"), SeatPlayer(3, 3, "c")])
    await real.surrender(state.game_id, 3)
    assert await real.leave_eliminated(state.game_id, 3) == 3
    pub.clear()
    target = state.get_valid_pawn_moves()[0]
    await real.move(state.game_id, 1, target.row, target.col)
    [event] = pub
    assert await d.deliver(event, 3) == []                        # 나간 사람
    assert [m["type"] for m in await d.deliver(event, 2)] == ["game_state", "turn_change"]


async def test_resync_reports_endings_missed_while_unsubscribed(real, fake_clock):
    from app.services.matchmaking import Matchmaking
    from app.services.rooms import Rooms

    rooms = Rooms(games={"maze_1p": real})
    d = Delivery(real, rooms, Matchmaking(games={"maze_1p": real}), clock=fake_clock)
    state = await start(real)
    await real.surrender(state.game_id, 2)                        # 끝났다 — 활동이 풀린다
    assert await d.resync(1) == []                                # 활동만 보면 아무것도 없다
    msgs = await d.resync(1, last=("game", state.game_id))
    assert [m["type"] for m in msgs] == ["game_state", "game_end"]

    room = await rooms.create_room("maze_1p", "duel", 7, "host")
    await rooms.join_room(room.code, 8, "guest")
    await rooms.leave_room(7)                                     # 해산
    [closed] = await d.resync(8, last=("room", room.code))
    assert closed["type"] == "player_left" and closed["payload"]["room_closed"] is True


async def test_void_event_on_running_state_never_builds_full_board(real, fake_clock):
    state = await start(real)
    d = Delivery(real, None, None, clock=fake_clock)
    end = await d._voided_end(state.game_id, 1, 9)                # 경합으로 진행 중 state 를 다시 읽었다
    assert end["payload"]["reason"] == "server_fault" and end["payload"]["full_board"] is None
