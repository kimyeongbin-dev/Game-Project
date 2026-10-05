"""
실시간 런타임 — 기동·종료 순서, 종료 신호 시각 기준 서버 유예(검토 M9), 큐 티커, 관측 (M3 7단계 B1)

실제 Redis(논리 DB 1), DB 없음. 구성요소 순서는 기록용 가짜로, 유예는 실제 게임 서비스 + 가짜 시계로 본다.
"""

import asyncio
from types import SimpleNamespace

import pytest

from app.services.identity import Identity
from app.services.matchmaking import Matchmaking
from app.services.maze_game import GAME, MazeGameService, SeatPlayer
from app.ws import runtime as runtime_module
from app.ws.connection_manager import ConnectionManager
from app.ws.delivery import Delivery
from app.ws.maze_handler import Session
from app.ws.runtime import QueueTicker, Realtime
from tests.ws.conftest import MockWebSocket
from tests.ws.live import build_handler


class Recorder:
    def __init__(self):
        self.calls: list[str] = []


class FakePart:
    """bus·sweeper·ticker 자리 — 호출 순서만 남긴다"""

    def __init__(self, name: str, rec: Recorder):
        self.name, self.rec = name, rec
        self.subscribed, self.resubscribes, self.running = False, 0, False
        self.last_tick_ok = self.last_tick_at_ms = None

    async def start(self):
        self.rec.calls.append(f"{self.name}.start")

    async def stop(self):
        self.rec.calls.append(f"{self.name}.stop")


class FakeMono:
    def __init__(self, clock):
        self.clock = clock

    def __call__(self) -> int:
        return self.clock.ms   # 가짜 시계와 같은 축 — 신호 시각 환산을 정확히 볼 수 있다


@pytest.fixture
def games(redis_client, fake_clock) -> MazeGameService:
    return MazeGameService(lambda: None, clock=fake_clock)


def make_runtime(games, fake_clock, rec: Recorder = None) -> Realtime:
    handler = build_handler(SimpleNamespace(), worker_id="w-test")
    handler.games = games
    rec = rec or Recorder()
    return Realtime(handler, games=games, bus=FakePart("bus", rec), sweeper=FakePart("sweeper", rec),
                    ticker=FakePart("ticker", rec), clock=fake_clock, worker_id="w-test",
                    monotonic_ms=FakeMono(fake_clock))


def session_of(user_id: int) -> Session:
    conn = SimpleNamespace(replaced=False, user_id=user_id)
    return Session(Identity(user_id, f"n{user_id}", 1000), conn)


async def start_game(games, users):
    return await games.create_game(
        mode="duel", is_ranked=False, players=[SeatPlayer(i + 1, u, f"n{u}") for i, u in enumerate(users)])


# ----- 순서 (B1) -----

async def test_start_and_stop_order(games, fake_clock, monkeypatch):
    rec = Recorder()
    rt = make_runtime(games, fake_clock, rec)

    async def fake_apply(recent, **kw):
        rec.calls.append("apply_on_shutdown")
        return 0
    monkeypatch.setattr(runtime_module, "apply_on_shutdown", fake_apply)

    await rt.start()
    assert rec.calls == ["bus.start", "sweeper.start", "ticker.start"] and rt.started

    async def slow_disconnect():
        await asyncio.sleep(0.2)
        rec.calls.append("disconnect.done")
    task = asyncio.create_task(slow_disconnect())
    rt._tasks.add(task)

    rec.calls.clear()
    await rt.stop()
    # 끊김 처리를 기다린 뒤 소급하고, 그다음 정지 — 버스는 마지막(그 사이 통지가 나갈 수 있다)
    assert rec.calls == ["disconnect.done", "apply_on_shutdown", "ticker.stop", "sweeper.stop", "bus.stop"]
    assert not rt.started


async def test_no_redis_means_no_realtime(games, fake_clock, monkeypatch):
    rec = Recorder()
    rt = make_runtime(games, fake_clock, rec)
    monkeypatch.setattr(runtime_module, "get_redis", lambda: None)
    await rt.start()
    await rt.stop()
    assert rec.calls == [] and not rt.started


def test_health_fields(games, fake_clock):
    rt = make_runtime(games, fake_clock)
    health = rt.health()
    assert set(health) == {"started", "worker_id", "connections", "bus", "sweeper", "draining"}
    assert set(health["bus"]) == {"name", "subscribed", "resubscribes"}
    assert set(health["sweeper"]) == {"running", "last_tick_ok", "last_tick_at_ms"}


# ----- 종료 신호 시각 (검토 M9) -----

async def _late_disconnect_then_shutdown(games, fake_clock, *, saw_signal: bool) -> bool:
    """신호 → 3 s 뒤에야 끊김 기록 → 다시 3 s 뒤 lifespan 종료. 그 좌석이 유예를 받았는가"""
    rt = make_runtime(games, fake_clock)
    await rt.start()
    state = await start_game(games, [1, 2])
    if saw_signal:
        rt.mark_draining()
    fake_clock.advance(3_000)
    await rt.handler.games.mark_connected(state.game_id, 2, worker_id="w-test")
    await rt.on_disconnect(session_of(2), 1012)   # 활동은 서비스가 정한다 — 이 유저는 게임 중
    fake_clock.advance(3_000)
    await rt.stop()
    clocks = await games.load_clocks(state.game_id)
    return bool(clocks.seat(2).grace)


async def test_grace_anchored_on_signal_time(games, fake_clock):
    """lifespan 시각 − 2 s 창 밖으로 밀린 끊김도 신호 이후라면 배포 끊김이다"""
    assert await _late_disconnect_then_shutdown(games, fake_clock, saw_signal=True)


async def test_without_signal_late_disconnect_gets_no_grace(games, fake_clock):
    """대조군 — 신호를 못 봤으면 lifespan 시각 기준(창 2 s)이라 3 s 전 끊김은 빠진다"""
    assert not await _late_disconnect_then_shutdown(games, fake_clock, saw_signal=False)


async def test_draining_converted_to_store_time(games, fake_clock):
    rt = make_runtime(games, fake_clock)
    assert await rt.draining_at_ms() is None
    t0 = fake_clock.ms
    rt.mark_draining()
    fake_clock.advance(1_500)
    rt.mark_draining()                     # 두 번째 신호는 시각을 바꾸지 않는다
    assert await rt.draining_at_ms() == t0


# ----- 큐 티커 -----

async def test_queue_ticker_sends_only_to_waiting_users(redis_client, games):
    manager = ConnectionManager()
    mm = Matchmaking(games={GAME: games})
    ticker = QueueTicker(manager, Delivery(games, None, mm))
    waiting, idle = MockWebSocket(), MockWebSocket()
    await manager.connect(waiting, 1, "a")
    await manager.connect(idle, 2, "b")
    await mm.join(GAME, "trio", 1, "a", 1000)
    assert await ticker.tick() == 1
    assert [m["type"] for m in waiting.sent_messages] == ["queue_status"]
    assert waiting.sent_messages[0]["payload"]["position"] == 1
    assert idle.sent_messages == []
