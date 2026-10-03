"""
데드라인 스위퍼 · 서버 유예 · 장애 처리 (maze.md §8, M3 6단계 커밋 3)

"워커가 2개면 무엇이 깨지는가?" 를 한 프로세스 안에서 본다 — 스위퍼 인스턴스 둘을 `gather` 로
동시에 돌리면 같은 Redis 에 서로 다른 풀 연결로 명령이 섞인다. 실제 프로세스 2개 확인은 7단계.
시각은 FakeClock(단조 시각도 같은 값) — 만료를 sleep 으로 기다리지 않는다. DB 는 쓰지 않는다.
"""

import asyncio
import json
import random

import pytest

from app.core.config import settings
from app.db import redis_keys as keys
from app.db.redis_lock import StoreUnavailable
from app.services import events, outages
from app.services.matchmaking import READY_DEADLINE_SEC, Matchmaking
from app.services.maze_clock import GameClocks
from app.services.maze_game import GAME, MazeGameService, SeatPlayer
from app.services.sweeper import DeadlineSweeper
from app.ws.server_grace import RecentDisconnects, apply_on_shutdown
from tests.conftest import FakeClock

S = 1000
INITIAL = settings.clock_initial_ms
BUDGET = settings.connection_budget_ms
GRACE = settings.server_grace_max_ms
LEASE = settings.sweeper_claim_lease_ms


class FlakyClock(FakeClock):
    """down 이면 Redis 가 죽은 것처럼 StoreUnavailable"""

    def __init__(self):
        super().__init__()
        self.down = False

    async def now_ms(self) -> int:
        if self.down:
            raise StoreUnavailable("redis down (test)")
        return self.ms


class RecordingPublisher:
    def __init__(self):
        self.events: list[events.Event] = []

    async def publish(self, event) -> None:
        self.events.append(event)

    def eliminations(self) -> list[events.Event]:
        return [e for e in self.events if e.hint.get("last_action", {}).get("kind") == "eliminated"]

    def kinds(self) -> list[str]:
        return [e.kind for e in self.events]


@pytest.fixture
def clock() -> FlakyClock:
    return FlakyClock()


@pytest.fixture
def pub() -> RecordingPublisher:
    return RecordingPublisher()


@pytest.fixture
def games(redis_client, pub, clock) -> MazeGameService:
    return MazeGameService(lambda: None, publisher=pub, clock=clock)


@pytest.fixture
def mm(games, pub, clock) -> Matchmaking:
    return Matchmaking(games={GAME: games}, rng_factory=lambda: random.Random(5), publisher=pub, clock=clock)


class Source:
    """DB 진행 중 목록의 가짜 — (game_id, 시작 ms)"""

    def __init__(self):
        self.rows: list[tuple[str, int]] = []
        self.calls = 0

    async def __call__(self):
        self.calls += 1
        return list(self.rows)


@pytest.fixture
def source() -> Source:
    return Source()


def make_sweeper(games, mm, clock, source) -> DeadlineSweeper:
    return DeadlineSweeper(games, mm, clock, in_progress_source=source, monotonic=lambda: clock.ms / 1000)


@pytest.fixture
def sweeper(games, mm, clock, source) -> DeadlineSweeper:
    return make_sweeper(games, mm, clock, source)


_next_user = [10_000]


async def start(games, mode="duel", seats=2):
    base = _next_user[0]
    _next_user[0] += seats
    users = list(range(base, base + seats))
    state = await games.create_game(
        mode=mode, is_ranked=False,
        players=[SeatPlayer(i + 1, uid, f"p{uid}") for i, uid in enumerate(users)],
    )
    return state, users


async def clocks_of(redis, game_id) -> GameClocks:
    return GameClocks.from_dict(json.loads(await redis.get(keys.game_clocks(game_id))))


async def score(redis, member):
    raw = await redis.zscore(keys.deadlines(GAME), member)
    return None if raw is None else int(raw)


# ----- 기본 만료 -----

async def test_tick_forfeits_expired_clock(games, sweeper, clock, pub, seat_mode):
    mode, seats = seat_mode
    state, _ = await start(games, mode, seats)
    clock.advance(INITIAL - 1)
    assert (await sweeper.tick()).expired == []
    clock.advance(1)
    report = await sweeper.tick()
    assert report.expired == [(state.game_id, 1, "time_forfeit")]
    assert len(pub.eliminations()) == 1


async def test_tick_forfeits_connection_clock(games, sweeper, clock, seat_mode):
    mode, seats = seat_mode
    state, users = await start(games, mode, seats)
    await games.mark_disconnected(state.game_id, users[-1])
    clock.advance(BUDGET)
    assert (await sweeper.tick()).expired == [(state.game_id, seats, "disconnect_forfeit")]


# ----- 이중 만료 없음 -----

async def test_two_sweepers_expire_each_deadline_once(games, mm, clock, source, pub, redis_client):
    states = [(await start(games))[0] for _ in range(20)]
    a, b = make_sweeper(games, mm, clock, source), make_sweeper(games, mm, clock, source)
    clock.advance(INITIAL + S)
    ra, rb = await asyncio.gather(a.tick(), b.tick())

    assert sorted(ra.expired + rb.expired) == sorted((s.game_id, 1, "time_forfeit") for s in states)
    assert not set(ra.claimed) & set(rb.claimed)          # 리스 클레임은 배타적이다
    assert len(pub.eliminations()) == 20
    for s in states:
        assert (await games.load_game(s.game_id)).seat(1).eliminated_order == 1


async def test_concurrent_expire_of_same_game_eliminates_once(games, clock, pub):
    """클레임이 겹쳐도(리스 만료 후 재클레임) 락 안 재계산이 한 번만 처리한다"""
    state, _ = await start(games, "trio", 3)
    clock.advance(INITIAL + S)
    results = await asyncio.gather(*(games.expire(state.game_id) for _ in range(4)))
    assert sorted(results, key=len) == [[], [], [], [(1, "time_forfeit")]]
    assert len(pub.eliminations()) == 1


async def test_action_racing_tick_charges_once(games, sweeper, clock, pub, redis_client):
    state, users = await start(games, "trio", 3)
    clock.advance(INITIAL + 1)
    target = state.get_valid_pawn_moves()[0]
    outcome, _ = await asyncio.gather(
        games.move(state.game_id, users[0], target.row, target.col), sweeper.tick(),
    )
    assert outcome.rejection == "not_in_game"
    assert len(pub.eliminations()) == 1
    assert (await clocks_of(redis_client, state.game_id)).seat(1).remaining_ms == -1  # 한 번만 차감


# ----- 누락 없음 -----

async def test_claim_then_crash_is_retried_after_lease(games, mm, clock, source, pub):
    state, _ = await start(games)
    crashed, survivor = make_sweeper(games, mm, clock, source), make_sweeper(games, mm, clock, source)
    clock.advance(INITIAL + S)
    assert await crashed.claim(clock.ms) == [keys.deadline_clock(state.game_id)]  # 처리 전에 죽는다

    assert (await survivor.tick()).claimed == []          # 리스 중에는 못 꺼낸다
    assert pub.eliminations() == []
    clock.advance(LEASE)
    assert (await survivor.tick()).expired == [(state.game_id, 1, "time_forfeit")]


async def test_stale_score_is_recomputed_not_trusted(games, sweeper, clock, redis_client, pub):
    state, _ = await start(games)
    member = keys.deadline_clock(state.game_id)
    await redis_client.zadd(keys.deadlines(GAME), {member: 0})
    report = await sweeper.tick()
    assert report.claimed == [member] and report.expired == []
    assert pub.eliminations() == []
    assert await score(redis_client, member) == clock.ms + INITIAL


async def test_member_of_missing_game_is_dropped(sweeper, redis_client, clock):
    member = keys.deadline_clock("no-such-game")
    await redis_client.zadd(keys.deadlines(GAME), {member: 0})
    await sweeper.tick()
    assert await score(redis_client, member) is None


# ----- 매치 ready -----

async def test_ready_deadline_expires_match(mm, sweeper, clock, pub, redis_client):
    for uid in (1, 2):
        result = await mm.join(GAME, "duel", uid, f"n{uid}", 1000)
    match = result.match
    await mm.mark_ready(match.match_id, 1)
    clock.advance(READY_DEADLINE_SEC * 1000 - 1)
    await sweeper.tick()
    assert events.MATCH_EXPIRED not in pub.kinds()
    clock.advance(1)
    await sweeper.tick()
    assert pub.kinds().count(events.MATCH_EXPIRED) == 1
    assert await score(redis_client, keys.deadline_ready(match.match_id)) is None


async def test_ready_member_without_match_is_dropped(sweeper, redis_client):
    member = keys.deadline_ready("gone")
    await redis_client.zadd(keys.deadlines(GAME), {member: 0})
    await sweeper.tick()
    assert await score(redis_client, member) is None


# ----- 서버 유예 (판단 7) -----

async def test_server_grace_freezes_both_clocks_for_deploy(games, sweeper, clock, redis_client):
    state, users = await start(games)
    recent = RecentDisconnects()
    d = (await games.mark_disconnected(state.game_id, users[0])).disconnected_at_ms
    recent.record(state.game_id, users[0], d)
    clock.advance(100)                                    # 소켓이 먼저 닫히고 lifespan 이 나중 (E3)
    assert await apply_on_shutdown(recent, games=games, clock=clock) == 1

    clock.advance(GRACE - 200)
    c = await clocks_of(redis_client, state.game_id)
    assert c.conn_remaining(1, clock.ms) == BUDGET
    assert c.game_remaining(1, 1, clock.ms) == INITIAL
    # 접속 시계 데드라인이 유예만큼 밀렸다
    assert await score(redis_client, keys.deadline_grace(state.game_id, 1)) == d + GRACE + BUDGET
    clock.advance(10 * S)                                 # 상한 30 s 이후로는 흐른다
    c = await clocks_of(redis_client, state.game_id)
    assert c.conn_remaining(1, clock.ms) == BUDGET - (clock.ms - d - GRACE)


async def test_disconnect_outside_window_gets_no_grace(games, clock):
    state, users = await start(games)
    recent = RecentDisconnects()
    d = (await games.mark_disconnected(state.game_id, users[1])).disconnected_at_ms
    recent.record(state.game_id, users[1], d)
    clock.advance(settings.server_grace_window_ms + 1)    # 배포보다 먼저 끊겼다
    assert await apply_on_shutdown(recent, games=games, clock=clock) == 0


async def test_reconnect_cuts_grace_window(games, clock, redis_client):
    state, users = await start(games)
    recent = RecentDisconnects()
    d = (await games.mark_disconnected(state.game_id, users[0])).disconnected_at_ms
    recent.record(state.game_id, users[0], d)
    await apply_on_shutdown(recent, games=games, clock=clock)
    clock.advance(5 * S)
    await games.mark_connected(state.game_id, users[0])
    clock.advance(40 * S)
    c = await clocks_of(redis_client, state.game_id)
    assert c.seat(1).conn_remaining_ms == BUDGET              # 유예 안의 끊김은 무료
    assert c.game_remaining(1, 1, clock.ms) == INITIAL - 40 * S  # 재접속 뒤로는 흐른다


async def test_reconnected_then_dropped_again_is_not_the_same_disconnection(games, clock):
    state, users = await start(games)
    recent = RecentDisconnects()
    d = (await games.mark_disconnected(state.game_id, users[1])).disconnected_at_ms
    recent.record(state.game_id, users[1], d)
    clock.advance(50)
    await games.mark_connected(state.game_id, users[1])     # 다른 워커로 붙었다(E4)
    clock.advance(50)
    await games.mark_disconnected(state.game_id, users[1])  # 그 워커에서 다시 끊김 — 이 워커 기록 아님
    assert await apply_on_shutdown(recent, games=games, clock=clock) == 0


async def test_grace_seat_turn_clock_waits_until_window_ends(games, clock, redis_client):
    """유예 중 남의 행동은 진행되고, 차례가 유예 좌석으로 오면 그 시계는 창 끝까지 멈춘다"""
    state, users = await start(games)
    recent = RecentDisconnects()
    d = (await games.mark_disconnected(state.game_id, users[1])).disconnected_at_ms
    recent.record(state.game_id, users[1], d)
    await apply_on_shutdown(recent, games=games, clock=clock)
    clock.advance(5 * S)
    target = state.get_valid_pawn_moves()[0]
    assert (await games.move(state.game_id, users[0], target.row, target.col)).rejection is None
    clock.advance(15 * S)
    c = await clocks_of(redis_client, state.game_id)
    assert c.game_remaining(2, 2, clock.ms) == INITIAL
    clock.advance(20 * S)                                   # 창 끝(d + 30 s) 뒤 10 s
    c = await clocks_of(redis_client, state.game_id)
    assert c.game_remaining(2, 2, clock.ms) == INITIAL - 10 * S


async def test_crash_gets_no_grace(games, sweeper, clock):
    """lifespan 이 돌지 않으면 유예도 없다 — 일반 끊김"""
    state, users = await start(games)
    await games.mark_disconnected(state.game_id, users[1])
    clock.advance(BUDGET)
    assert (await sweeper.tick()).expired == [(state.game_id, 2, "disconnect_forfeit")]


# ----- Redis 장애 (판단 8) -----

async def outage(sweeper, clock, *, before_fail_ms, down_ms):
    await sweeper.tick()                     # 마지막 성공
    clock.advance(before_fail_ms)
    clock.down = True
    assert (await sweeper.tick()).ok is False
    clock.advance(down_ms)
    assert (await sweeper.tick()).ok is False
    clock.down = False
    return await sweeper.tick()


async def test_outage_is_recorded_and_exempt_from_clocks(games, sweeper, clock, redis_client):
    state, _ = await start(games)
    t_fail_start = clock.ms + S
    report = await outage(sweeper, clock, before_fail_ms=S, down_ms=20 * S)
    assert report.outage == (t_fail_start, clock.ms)
    exempt = await outages.read(redis_client, 0)
    c = await clocks_of(redis_client, state.game_id)
    assert c.game_remaining(1, 1, clock.ms, exempt) == INITIAL - S   # 장애 20 s 는 빠진다
    # 소진 판정도 같은 면제를 쓴다 — 원래 기한에는 아직 아니다
    clock.set(c.started_at_ms + INITIAL)
    assert await games.expire(state.game_id) == []


async def test_short_outage_is_not_recorded(sweeper, clock, redis_client):
    report = await outage(sweeper, clock, before_fail_ms=S, down_ms=settings.store_outage_min_ms - 1)
    assert report.outage is None
    assert await redis_client.zcard(keys.store_outages()) == 0


async def test_stall_without_failures_is_not_an_outage(games, sweeper, clock, redis_client):
    """워커가 멈췄던 것과 Redis 장애를 구분한다 — 실패한 호출이 없으면 기록하지 않는다"""
    state, _ = await start(games)
    await sweeper.tick()
    clock.advance(settings.store_outage_void_sec * 1000 + S)
    report = await sweeper.tick()
    assert report.outage is None and report.voided == []
    assert await redis_client.zcard(keys.store_outages()) == 0


async def test_long_outage_voids_running_games_once(games, mm, clock, source, pub, redis_client):
    old = [(await start(games))[0] for _ in range(3)]
    a, b = make_sweeper(games, mm, clock, source), make_sweeper(games, mm, clock, source)
    for s in (a, b):
        await s.tick()
    clock.advance(S)
    clock.down = True
    await asyncio.gather(a.tick(), b.tick())
    clock.advance(settings.store_outage_void_sec * 1000)
    clock.down = False
    fresh, _ = await start(games)                        # 복구 직후 생긴 게임 — 대상 아님
    ra, rb = await asyncio.gather(a.tick(), b.tick())

    assert sorted(ra.voided + rb.voided) == sorted(s.game_id for s in old)
    assert pub.kinds().count(events.GAME_VOIDED) == 3
    for s in old:
        assert await redis_client.exists(keys.game_state(s.game_id)) == 0
    assert await redis_client.exists(keys.game_state(fresh.game_id)) == 1


# ----- 상태 유실 (판단 8) -----

async def test_lost_state_is_voided_once(games, mm, clock, source, pub, redis_client):
    state, users = await start(games)
    source.rows = [(state.game_id, clock.ms)]
    await redis_client.delete(keys.game_state(state.game_id))
    clock.advance(settings.lost_game_min_age_sec * 1000)
    a, b = make_sweeper(games, mm, clock, source), make_sweeper(games, mm, clock, source)
    ra, rb = await asyncio.gather(a.tick(), b.tick())
    assert ra.voided + rb.voided == [state.game_id]
    assert source.calls == 1                              # 점검 락 — 주기마다 한 워커
    assert pub.kinds().count(events.GAME_VOIDED) == 1
    for uid in users:
        assert await redis_client.get(keys.user_activity(uid)) is None


async def test_young_game_without_state_is_not_voided(games, sweeper, clock, source, pub, redis_client):
    state, _ = await start(games)
    source.rows = [(state.game_id, clock.ms)]
    await redis_client.delete(keys.game_state(state.game_id))   # 생성 중(DB 먼저)과 구분이 안 된다
    clock.advance(settings.lost_game_min_age_sec * 1000 - 1)
    assert (await sweeper.tick()).voided == []
    assert events.GAME_VOIDED not in pub.kinds()


async def test_present_state_is_never_voided_by_scan(games, sweeper, clock, source, pub):
    state, _ = await start(games)
    source.rows = [(state.game_id, clock.ms)]
    clock.advance(settings.lost_game_min_age_sec * 1000 + S)
    assert (await sweeper.tick()).voided == []


async def test_void_lost_game_twice_notifies_once(games, pub, redis_client):
    state, _ = await start(games)
    await redis_client.delete(keys.game_state(state.game_id))
    assert await games.void_lost_game(state.game_id) is True
    assert await games.void_lost_game(state.game_id) is False
    assert pub.kinds().count(events.GAME_VOIDED) == 1


async def test_concurrent_voids_notify_once(games, pub, redis_client):
    """여러 워커가 같은 게임을 동시에 무효로 닫아도 통지·activity 해제는 한 번 — 락 안에서 키를 지운 쪽만"""
    lost, _ = await start(games)
    await redis_client.delete(keys.game_state(lost.game_id))
    running, _ = await start(games)
    lost_results = await asyncio.gather(*(games.void_lost_game(lost.game_id) for _ in range(4)))
    running_results = await asyncio.gather(*(games.void_game(running.game_id) for _ in range(4)))
    assert sorted(lost_results) == [False, False, False, True]
    assert sorted(running_results) == [False, False, False, True]
    assert pub.kinds().count(events.GAME_VOIDED) == 2


# ----- 루프 -----

async def test_loop_processes_and_stops(games, sweeper, clock, pub, monkeypatch):
    monkeypatch.setattr(settings, "sweeper_interval_ms", 10)
    state, _ = await start(games)
    clock.advance(INITIAL)
    await sweeper.start()
    try:
        for _ in range(100):
            if pub.eliminations():
                break
            await asyncio.sleep(0.01)
    finally:
        await sweeper.stop()
    assert len(pub.eliminations()) == 1


def test_recent_disconnects_keeps_only_recent():
    recent = RecentDisconnects(keep_ms=1000)
    recent.record("g", 1, 0)
    recent.record("g", 2, 500)
    recent.record("g", 3, 2000)
    assert [e.user_id for e in recent.since(0)] == [3]
    assert [e.user_id for e in recent.since(2000)] == [3]
