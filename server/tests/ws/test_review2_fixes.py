"""
독립 검토 #2 회귀 — 재구독 claim 이 소유를 되돌리지 않음(Q1), 끊긴 뒤 시작한 게임·남의 연결(Q2), 락 자기 교착(Q5),
행동 경로 소유(Q11), 연결 표시 해제 재시도(Q10)  (docs/research/2026-10-06-M3-7단계-독립검토-2.md)

검토자의 재현 테스트(저장소 밖)를 옮겼다. 실제 Redis(논리 DB 1), DB 없음.
"""

import asyncio
from types import SimpleNamespace

import pytest

from app.db import redis_keys as keys
from app.db.redis_lock import redis_lock
from app.services.identity import Identity
from app.services.maze_game import MazeGameService, SeatPlayer
from app.ws.bus import EventBus
from app.ws.connection_manager import ConnectionManager
from app.ws.delivery import Delivery
from app.ws.maze_handler import Session
from tests.ws.conftest import MockWebSocket
from tests.ws.test_review_fixes import Flaky, rt_for, session


@pytest.fixture
def real(redis_client, fake_clock) -> MazeGameService:
    return MazeGameService(lambda: None, clock=fake_clock)


async def start(games):
    return await games.create_game(mode="duel", is_ranked=False,
                                   players=[SeatPlayer(1, 1, "a"), SeatPlayer(2, 2, "b")])


# ----- Q1 -----

async def test_resubscribe_does_not_hand_the_seat_back_to_a_stale_connection(real, redis_client, fake_clock):
    state = await start(real)
    manager = ConnectionManager()
    bus = EventBus(manager, Delivery(real, None, None, clock=fake_clock))
    ws = MockWebSocket()
    old = await manager.connect(ws, 2, "b")
    old.conn_id = "wA:old"
    await real.mark_connected(state.game_id, 2, owner="wA:old")
    # 구독이 끊긴 사이 같은 계정이 다른 워커로 — 교체 통지를 놓쳤다
    await redis_client.set(keys.user_conn(2), "wB:new")
    await real.mark_connected(state.game_id, 2, owner="wB:new")

    await bus._resync_all()                                   # 재구독 직후
    await asyncio.sleep(0.05)
    assert ws.closed and ws.close_code == 4000                # 옛 연결은 닫힌다
    assert (await real.load_clocks(state.game_id)).seat(2).owner == "wB:new"

    bus._claim(state.game_id, 2)                              # 남은 연결이 없으니 아무 일도 없다
    await asyncio.sleep(0.05)
    assert (await real.load_clocks(state.game_id)).seat(2).owner == "wB:new"


async def test_claim_only_for_the_current_connection(real, redis_client, fake_clock):
    state = await start(real)
    manager = ConnectionManager()
    bus = EventBus(manager, Delivery(real, None, None, clock=fake_clock))
    conn = await manager.connect(MockWebSocket(), 2, "b")
    conn.conn_id = "wA:old"
    await redis_client.set(keys.user_conn(2), "wB:new")       # Redis 가 아는 현재 연결은 다른 것
    bus._claim(state.game_id, 2)
    await asyncio.sleep(0.05)
    assert (await real.load_clocks(state.game_id)).seat(2).owner is None
    await redis_client.set(keys.user_conn(2), "wA:old")
    bus._claim(state.game_id, 2)
    await asyncio.sleep(0.05)
    assert (await real.load_clocks(state.game_id)).seat(2).owner == "wA:old"


# ----- Q2 -----

async def test_late_resolved_retry_does_not_hit_a_game_started_after_it(real, redis_client, fake_clock):
    """방에서 Redis 순간 장애 중 끊긴 연결 c0 → 같은 유저가 c1 로 돌아와 새 게임 시작 → c0 재시도가 그 게임에 닿지 않는다"""
    rt = rt_for(real, fake_clock)
    calls = {"n": 0}
    original = rt.handler._activity

    async def blip(uid):
        calls["n"] += 1
        if calls["n"] == 1:
            from app.db.redis_lock import StoreUnavailable
            raise StoreUnavailable("blip")
        return await original(uid)

    rt.handler._activity = blip
    await rt._record_disconnect(session(2, "w1:c0"), 1006)
    assert len(rt.pending) == 1
    fake_clock.advance(800)
    await redis_client.set(keys.user_conn(2), "w1:c1")
    state = await start(real)                                 # 그 뒤 시작 — 좌석 owner 는 아직 기록 전(None)
    fake_clock.advance(300)
    await rt.retry_pending()
    if rt._retry_task:
        rt._retry_task.cancel()
    assert (await real.load_clocks(state.game_id)).seat(2).connected


async def test_unowned_seat_ignores_a_disconnect_from_another_connection(real, redis_client):
    """owner 기록 전 좌석 — 그 유저의 지금 연결 표시가 다른 연결이면 그 끊김은 옛 연결의 것이다"""
    state = await start(real)
    await redis_client.set(keys.user_conn(2), "wA:live")
    assert await real.mark_disconnected(state.game_id, 2, owner="wA:stale") is None
    assert (await real.load_clocks(state.game_id)).seat(2).connected
    await redis_client.delete(keys.user_conn(2))              # 표시가 지워졌다 = 진짜로 떠났다
    assert await real.mark_disconnected(state.game_id, 2, owner="wA:live") is not None


# ----- Q5 -----

async def test_lock_whose_set_already_landed_is_mine(redis_client, monkeypatch):
    """SET NX 가 실행된 뒤 응답만 잃고 재시도했다 — 값이 내 토큰이면 기다리지 않고 획득이다"""
    import secrets as real_secrets

    monkeypatch.setattr(real_secrets, "token_hex", lambda n=16: "fixed-token")
    await redis_client.set("game:q5:lock", "fixed-token", px=5_000)   # 첫 시도가 남긴 락
    loop = asyncio.get_running_loop()
    t = loop.time()
    async with redis_lock(redis_client, "game:q5:lock", wait_ms=2_000) as token:
        assert token == "fixed-token"
    assert loop.time() - t < 0.5
    assert await redis_client.get("game:q5:lock") is None             # 해제도 된다


def test_retry_only_on_connection_errors():
    from redis.exceptions import ConnectionError, TimeoutError

    from app.db.redis import _retry

    retry = _retry()
    assert retry._retries == 1
    assert ConnectionError in retry._supported_errors and TimeoutError not in retry._supported_errors


# ----- Q11 -----

async def test_action_records_the_connection_as_owner(real, fake_clock):
    state = await start(real)
    await real.mark_disconnected(state.game_id, 1)
    target = state.get_valid_pawn_moves()[0]
    outcome = await real.move(state.game_id, 1, target.row, target.col, owner="wA:c9")
    assert outcome.rejection is None
    seat = (await real.load_clocks(state.game_id)).seat(1)
    assert seat.connected and seat.owner == "wA:c9"            # 행동 = 재접속 — 크래시 때 스위퍼가 찾는다


# ----- Q10 -----

async def test_failed_release_is_retried_before_recording(real, redis_client, fake_clock, monkeypatch):
    state = await start(real)
    await redis_client.set(keys.user_conn(2), "w1:c2")
    await real.mark_connected(state.game_id, 2, owner="w1:c2")
    rt = rt_for(real, fake_clock)
    results = iter([False, False])                            # 연결이 끝날 때와 첫 기록 시도 때 해제가 실패한다(Redis 순간 장애)
    original = rt.handler.release_session

    async def flaky_release(s):
        if next(results, True) is False:
            return False
        return await original(s)

    monkeypatch.setattr(rt.handler, "release_session", flaky_release)
    s = Session(Identity(2, "b", 1000), SimpleNamespace(replaced=False, user_id=2, conn_id="w1:c2"))
    t0 = fake_clock.ms
    await rt._record_disconnect(s, 1006)
    assert len(rt.pending) == 1 and rt.pending[0].session is s    # 표시를 못 지웠으면 기록도 미룬다
    fake_clock.advance(1_000)
    assert await rt.retry_pending() == 1
    if rt._retry_task:
        rt._retry_task.cancel()
    seat = (await real.load_clocks(state.game_id)).seat(2)
    assert not seat.connected and seat.disconnected_at_ms == t0    # 원래 시각
    assert await redis_client.get(keys.user_conn(2)) is None
    assert rt.pending == []


async def test_retry_older_than_the_game_is_ignored_even_without_a_live_marker(real, fake_clock):
    """연결 표시가 없어 대조가 불가능해도(이미 떠났다) 끊긴 시각이 게임 시작 전이면 그 게임의 좌석에 적용하지 않는다(Q2)"""
    t_gone = fake_clock.ms
    fake_clock.advance(1_000)
    state = await start(real)
    assert await real.redo_disconnect(state.game_id, 2, owner="w1:c0", at_ms=t_gone) is None
    assert (await real.load_clocks(state.game_id)).seat(2).connected


# ----- Q7 -----

async def test_resync_reports_an_ending_once(real, redis_client, fake_clock):
    """끝난 게임을 재동기화로 한 번 알리면 그 활동을 잊는다 — 다음 재구독에서 결과를 다시 보내지 않는다"""
    state = await start(real)
    manager = ConnectionManager()
    bus = EventBus(manager, Delivery(real, None, None, clock=fake_clock))
    ws = MockWebSocket()
    conn = await manager.connect(ws, 1, "a")
    conn.last_activity = ("game", state.game_id)
    await real.surrender(state.game_id, 2)                        # 끝났다 — 활동이 풀린다
    await bus._resync_all()
    assert [m["type"] for m in ws.sent_messages] == ["game_state", "game_end"]
    assert conn.last_activity is None
    ws.sent_messages.clear()
    await bus._resync_all()
    assert ws.sent_messages == []


# ----- Q13 -----

def test_periodic_bursts_cannot_dodge_1008(monkeypatch):
    """쉬었다 연타하기를 반복해도 위반은 초당 하나씩만 잊는다 — 결국 1008"""
    from app.core.config import settings
    from app.ws.rate_limit import TokenBucket

    monkeypatch.setattr(settings, "ws_violation_close", 50)
    t = {"now": 0.0}
    bucket = TokenBucket(3, 1.0, lambda: t["now"])
    closed = False
    for _ in range(10):
        t["now"] += 4.0                                           # 버스트를 다시 채울 만큼 쉰다
        for _ in range(3 + 30):                                   # 버스트 3 + 위반 30
            bucket.allow()
        if bucket.exhausted:
            closed = True
            break
    assert closed


# ----- Q14 -----

def test_production_health_hides_worker_details(monkeypatch):
    from app.core.config import settings
    from tests.ws.test_runtime import FakePart
    from app.ws.runtime import Realtime
    from tests.ws.live import build_handler

    parts = SimpleNamespace(calls=[])
    rt = Realtime(build_handler(SimpleNamespace()), bus=FakePart("b", parts), sweeper=FakePart("s", parts),
                  ticker=FakePart("t", parts))
    monkeypatch.setattr(settings, "environment", "production")
    monkeypatch.setattr(settings, "ws_expose_worker", False)
    health = rt.health()
    assert "worker_id" not in health and "connections" not in health and "name" not in health["bus"]
    monkeypatch.setattr(settings, "ws_expose_worker", True)
    assert "worker_id" in rt.health()


async def test_claim_checks_the_current_connection_under_the_game_lock(real, redis_client):
    """게임 시작의 소유 기록이 확인 뒤 락을 기다리는 사이 새 연결이 소유를 가져갔다 — 그 기록은 소유를 되돌리지 않는다
    (다중 워커 실측 S8: 게임 시작 0.05 s 뒤 다른 워커로 재접속)"""
    state = await start(real)
    await redis_client.set(keys.user_conn(2), "wB:new")            # 새 연결이 표시를 쓰고
    await real.mark_connected(state.game_id, 2, owner="wB:new")    # 소유를 가져갔다
    # 옛 워커의 claim — 락 밖 확인은 이미 지났다(그때는 옛 연결이 현재였다)
    assert not await real.mark_connected(state.game_id, 2, owner="wA:old", only_if_current=True)
    assert (await real.load_clocks(state.game_id)).seat(2).owner == "wB:new"
    # 현재 연결의 기록은 된다
    await redis_client.set(keys.user_conn(1), "wA:c1")
    await real.mark_connected(state.game_id, 1, owner="wA:c1", only_if_current=True)
    assert (await real.load_clocks(state.game_id)).seat(1).owner == "wA:c1"



# ----- 독립 검토 #3 높음 1 — 소유 불변식(owner = 그 유저의 현재 연결)을 welcome·행동·끊김 모두 락 안에서 -----

async def test_late_welcome_of_a_replaced_connection_does_not_take_the_seat_back(real, redis_client):
    """C2·C3 순으로 재접속, C3 의 welcome 이 먼저 커밋되고 C2 의 welcome 이 늦게 — 소유는 C3 그대로, C2 의 끊김은 무시"""
    state = await start(real)
    await redis_client.set(keys.user_conn(2), "wB:c3")                 # C3 가 표시를 마지막으로 썼다
    await real.mark_connected(state.game_id, 2, owner="wB:c3")
    assert not await real.mark_connected(state.game_id, 2, owner="wA:c2")   # 늦은 C2 welcome
    assert (await real.load_clocks(state.game_id)).seat(2).owner == "wB:c3"
    assert await real.mark_disconnected(state.game_id, 2, owner="wA:c2") is None   # 밀려난 C2 가 닫힌다
    assert (await real.load_clocks(state.game_id)).seat(2).disconnected_at_ms is None


async def test_action_from_a_replaced_connection_is_played_but_does_not_move_ownership(real, redis_client):
    state = await start(real)
    await redis_client.set(keys.user_conn(1), "wB:new")
    await real.mark_connected(state.game_id, 1, owner="wB:new")
    target = state.get_valid_pawn_moves()[0]
    result = await real.move(state.game_id, 1, target.row, target.col, owner="wA:old")   # 교체 통지 전 옛 연결의 행동
    assert result.rejection is None
    assert (await real.load_clocks(state.game_id)).seat(1).owner == "wB:new"


async def test_disconnect_while_another_live_connection_is_current_is_ignored_even_if_owner_matches(
        real, redis_client, fake_clock):
    """소유가 (어떤 경로로든) 옛 연결로 남았어도, 지금 연결이 다른 살아 있는 워커에 있으면 옛 연결의 끊김은 기록하지 않는다"""
    state = await start(real)
    await real.mark_connected(state.game_id, 2, owner="wA:old")       # 표시 없음 → 기록된다
    await redis_client.set(keys.user_conn(2), "wB:new")
    await redis_client.zadd(keys.workers(), {"wB": fake_clock.ms})    # wB 는 살아 있다
    assert await real.mark_disconnected(state.game_id, 2, owner="wA:old") is None
    assert (await real.load_clocks(state.game_id)).seat(2).disconnected_at_ms is None


async def test_disconnect_is_recorded_when_the_current_connection_belongs_to_a_dead_worker(
        real, redis_client, fake_clock):
    """지금 연결의 워커가 죽었다 — 그 연결은 끊김을 기록하지 못한다. 옛 연결의 끊김을 버리면 좌석이 영영 "연결 중"이다"""
    state = await start(real)
    await real.mark_connected(state.game_id, 2, owner="wA:old")
    await redis_client.set(keys.user_conn(2), "wB:new")
    await redis_client.zadd(keys.workers(), {"wB": fake_clock.ms - 60_000})
    assert await real.mark_disconnected(state.game_id, 2, owner="wA:old") is not None


async def test_only_if_current_without_owner_is_refused(real):
    state = await start(real)
    with pytest.raises(ValueError):
        await real.mark_connected(state.game_id, 1, owner=None, only_if_current=True)


async def test_claim_seat_uses_the_in_lock_current_connection_check():
    """배선 — Delivery.claim_seat 가 락 안 대조(only_if_current)를 켠다(검토 #3: 서비스 직접 호출 테스트만 있었다)"""
    calls = []

    class Games:
        async def mark_connected(self, game_id, user_id, **kw):
            calls.append(kw)
            return False

    await Delivery(Games(), None, None).claim_seat("g", 7, "wA:c")
    assert calls == [{"owner": "wA:c", "only_if_current": True}]
