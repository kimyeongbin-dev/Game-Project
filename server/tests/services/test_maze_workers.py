"""
워커 크래시·수신 시각·유예 격리 — 독립 검토 H4·H7·H8·L21·L26 (M3 6단계 커밋 6-F3)

워커는 한 프로세스 안의 스위퍼 인스턴스로 흉내 낸다(워커 id 만 다르다). 시각은 FakeClock. DB 는 쓰지 않는다.
"""

import asyncio
import json
import random

import pytest

from app.core.config import settings
from app.db import redis_keys as keys
from app.db.redis import get_redis
from app.services import events
from app.services.activity import MultiplayerError
from app.services.matchmaking import READY_DEADLINE_SEC, Matchmaking
from app.services.maze_clock import GameClocks
from app.services.maze_game import GAME, GraceEntry, MazeGameService, SeatPlayer
from app.services.sweeper import DeadlineSweeper

S = 1000
INITIAL = settings.clock_initial_ms
INCREMENT = settings.clock_increment_ms
BUDGET = settings.connection_budget_ms
TIMEOUT = settings.worker_heartbeat_timeout_ms


class RecordingPublisher:
    def __init__(self):
        self.events: list[events.Event] = []

    async def publish(self, event) -> None:
        self.events.append(event)

    def kinds(self) -> list[str]:
        return [e.kind for e in self.events]


@pytest.fixture
def pub() -> RecordingPublisher:
    return RecordingPublisher()


@pytest.fixture
def games(redis_client, pub, fake_clock) -> MazeGameService:
    return MazeGameService(lambda: None, publisher=pub, clock=fake_clock)


@pytest.fixture
def mm(games, pub, fake_clock) -> Matchmaking:
    return Matchmaking(games={GAME: games}, rng_factory=lambda: random.Random(2), publisher=pub, clock=fake_clock)


async def no_sources():
    return []


def worker(games, mm, clock, worker_id: str) -> DeadlineSweeper:
    return DeadlineSweeper(games, mm, clock, in_progress_source=no_sources, worker_id=worker_id)


async def passes(clock, ms: int) -> None:
    """건강한 시간 경과 — 전역 하트비트 공백(장애)은 없다"""
    clock.advance(ms)
    await get_redis().set(keys.store_alive(), clock.ms)


async def start(games, mode="duel", seats=2, first=801):
    users = list(range(first, first + seats))
    state = await games.create_game(
        mode=mode, is_ranked=False,
        players=[SeatPlayer(i + 1, uid, f"p{uid}") for i, uid in enumerate(users)],
    )
    return state, users


async def clocks_of(redis, game_id) -> GameClocks:
    return GameClocks.from_dict(json.loads(await redis.get(keys.game_clocks(game_id))))


# ----- H4 — 크래시한 워커의 연결 -----

async def test_crashed_workers_seat_starts_its_connection_clock(games, mm, fake_clock, pub, redis_client, seat_mode):
    mode, seats = seat_mode
    state, users = await start(games, mode, seats)
    doomed, survivor = worker(games, mm, fake_clock, "w-doomed"), worker(games, mm, fake_clock, "w-survivor")
    for uid in users:
        await games.mark_connected(state.game_id, uid, owner="w-doomed" if uid == users[-1] else "w-survivor")
    assert await redis_client.zrange(keys.worker_seats("w-doomed"), 0, -1) == [keys.seat_member(state.game_id, seats)]
    await doomed.tick()
    last_beat = fake_clock.ms
    await survivor.tick()

    await passes(fake_clock, TIMEOUT + S)          # doomed 는 SIGKILL — 하트비트도 끊김 핸들러도 없다
    report = await survivor.tick()
    assert report.dropped == [(state.game_id, seats)]
    seat = (await clocks_of(redis_client, state.game_id)).seat(seats)
    assert seat.disconnected_at_ms == last_beat and seat.owner is None
    assert events.SEAT_DISCONNECTED in pub.kinds()
    assert await redis_client.zscore(keys.workers(), "w-doomed") is None   # 다 처리한 죽은 워커는 잊는다
    assert await redis_client.exists(keys.worker_seats("w-doomed")) == 0

    await passes(fake_clock, BUDGET - (fake_clock.ms - last_beat))
    assert (await survivor.tick()).expired == [(state.game_id, seats, "disconnect_forfeit")]


async def test_seat_moved_to_another_worker_is_not_dropped(games, mm, fake_clock, redis_client):
    state, users = await start(games)
    old, new = worker(games, mm, fake_clock, "w-old"), worker(games, mm, fake_clock, "w-new")
    await games.mark_connected(state.game_id, users[1], owner="w-old")
    await old.tick()
    await games.mark_connected(state.game_id, users[1], owner="w-new")  # 끊김 없이 다른 워커로 붙었다(E4)
    assert await redis_client.zcard(keys.worker_seats("w-old")) == 0
    await passes(fake_clock, TIMEOUT + S)
    assert (await new.tick()).dropped == []
    assert (await clocks_of(redis_client, state.game_id)).seat(2).connected


async def test_stale_index_entry_does_not_drop_a_moved_seat(games, mm, fake_clock, redis_client):
    """경쟁 창 — 스위퍼가 죽은 워커의 색인을 읽은 뒤, 락을 잡기 전에 좌석이 다른 워커로 옮겨 갔다.
    색인 항목은 낡았고, 좌석 소유 확인이 그것을 걸러야 한다"""
    state, users = await start(games)
    old, new = worker(games, mm, fake_clock, "w-old"), worker(games, mm, fake_clock, "w-new")
    await old.tick()
    await games.mark_connected(state.game_id, users[1], owner="w-new")
    await redis_client.zadd(keys.worker_seats("w-old"), {keys.seat_member(state.game_id, 2): 0})
    await passes(fake_clock, TIMEOUT + S)
    assert (await new.tick()).dropped == []
    seat = (await clocks_of(redis_client, state.game_id)).seat(2)
    assert seat.connected and seat.owner == "w-new"
    assert await redis_client.zcard(keys.worker_seats("w-old")) == 0     # 낡은 항목은 치운다


async def test_live_worker_is_never_reaped(games, mm, fake_clock):
    state, users = await start(games)
    a, b = worker(games, mm, fake_clock, "w-a"), worker(games, mm, fake_clock, "w-b")
    await games.mark_connected(state.game_id, users[0], owner="w-a")
    for _ in range(3):
        await passes(fake_clock, TIMEOUT // 2)
        await a.tick()
        assert (await b.tick()).dropped == []


async def test_finished_game_clears_owner_index(games, redis_client):
    state, users = await start(games)
    await games.mark_connected(state.game_id, users[0], owner="w-x")
    await games.mark_connected(state.game_id, users[1], owner="w-x")
    await games.surrender(state.game_id, users[0])
    assert await redis_client.zcard(keys.worker_seats("w-x")) == 0


# ----- H7 — 유예 소급은 하나가 실패해도 나머지를 처리한다 -----

async def test_server_grace_isolates_a_busy_game(games, fake_clock, redis_client, monkeypatch):
    busy, busy_users = await start(games, first=901)
    calm, calm_users = await start(games, first=911)
    entries = []
    for state, users in ((busy, busy_users), (calm, calm_users)):
        d = (await games.mark_disconnected(state.game_id, users[1])).disconnected_at_ms
        entries.append(GraceEntry(state.game_id, users[1], d))
    monkeypatch.setattr(settings, "game_lock_wait_ms", 0)
    await redis_client.set(keys.game_lock(busy.game_id), "held", px=60_000)

    assert await games.apply_server_grace(entries) == 1
    assert (await clocks_of(redis_client, calm.game_id)).seat(2).grace
    assert not (await clocks_of(redis_client, busy.game_id)).seat(2).grace
    await redis_client.delete(keys.game_lock(busy.game_id))


# ----- H8 — 수신 시각, 락 없는 거절 -----

async def test_off_turn_spam_is_rejected_without_the_lock(games, redis_client, monkeypatch):
    state, users = await start(games)
    monkeypatch.setattr(settings, "game_lock_wait_ms", 0)
    await redis_client.set(keys.game_lock(state.game_id), "held", px=60_000)
    target = state.get_valid_pawn_moves()[0]
    for _ in range(20):   # 락이 잡혀 있어도 GameBusy 가 아니라 즉시 not_your_turn
        assert (await games.move(state.game_id, users[1], target.row, target.col)).rejection == "not_your_turn"
    await redis_client.delete(keys.game_lock(state.game_id))


async def test_lock_wait_is_not_charged_to_the_actor(games, fake_clock, redis_client):
    """수신 시각으로 정산한다 — 남이 락을 잡고 있던 시간은 행위자의 시계에서 빠지지 않는다"""
    state, users = await start(games)
    await passes(fake_clock, 3 * S)
    await redis_client.set(keys.game_lock(state.game_id), "held", px=60_000)
    target = state.get_valid_pawn_moves()[0]
    task = asyncio.create_task(games.move(state.game_id, users[0], target.row, target.col))
    await asyncio.sleep(0.05)                 # 수신 시각을 찍고 락을 기다리는 중
    fake_clock.advance(1500)                  # 그 사이 1.5 s 가 흐른다
    await redis_client.delete(keys.game_lock(state.game_id))
    assert (await task).rejection is None
    assert (await clocks_of(redis_client, state.game_id)).seat(1).remaining_ms == INITIAL - 3 * S + INCREMENT


async def test_expired_current_seat_sends_off_turn_action_to_the_slow_path(games, fake_clock):
    """현재 좌석 시계가 이미 0 이면 차례가 넘어간 것일 수 있다 — 스냅샷으로 거절하지 않는다"""
    state, users = await start(games, "trio", 3)
    fake_clock.advance(INITIAL + S)
    target = _moves_for(await games.load_game(state.game_id), 2)[0]
    outcome = await games.move(state.game_id, users[1], target.row, target.col)
    assert outcome.state.seat(1).is_eliminated            # 정산이 먼저 일어났다
    assert outcome.rejection is None                      # 좌석 2 의 차례가 됐고 이동이 수락됐다


def _moves_for(state, seat_no):
    """좌석 seat_no 가 지금 둘 수 있는 이동 (엔진의 현재 좌석을 잠시 바꿔 계산)"""
    original = state.current_seat_no
    state.current_seat_no = seat_no
    try:
        return state.get_valid_pawn_moves()
    finally:
        state.current_seat_no = original


# ----- L21 — 시각 출처가 뒤로 뛰어도 -----

async def test_clock_going_backwards_does_not_rewind_turn_start(games, fake_clock, redis_client):
    state, users = await start(games)
    t0 = fake_clock.ms
    fake_clock.set(t0 + 10 * S)
    await _move(games, state.game_id, users[0])           # 좌석 2 의 차례가 t0+10 s 에 시작
    fake_clock.set(t0 + 5 * S)                            # Redis 시각이 5 s 뒤로 뛰었다
    await _move(games, state.game_id, users[1])
    c = await clocks_of(redis_client, state.game_id)
    assert c.turn_started_at_ms == t0 + 10 * S            # 뒤로 가지 않는다
    assert c.seat(2).remaining_ms == INITIAL + INCREMENT  # 음수 경과도, 되감기도 없다


async def _move(games, game_id, user_id):
    state = await games.load_game(game_id)
    target = state.get_valid_pawn_moves()[0]
    outcome = await games.move(game_id, user_id, target.row, target.col)
    assert outcome.rejection is None, outcome.rejection
    return outcome


# ----- L26 — 기한 지난 ready -----

async def test_ready_after_deadline_is_refused(mm, fake_clock):
    for uid in (1, 2):
        result = await mm.join(GAME, "duel", uid, f"n{uid}", 1000)
    match = result.match
    await mm.mark_ready(match.match_id, 1)
    fake_clock.advance(READY_DEADLINE_SEC * 1000)
    with pytest.raises(MultiplayerError) as exc:
        await mm.mark_ready(match.match_id, 2)
    assert exc.value.code == "not_in_queue"


async def test_global_outage_does_not_make_live_workers_look_dead(games, mm, fake_clock, redis_client):
    """전역 Redis 장애(모든 워커의 하트비트가 함께 멈춤) 뒤 먼저 돈 워커가 살아 있는 다른 워커를 죽었다고 보지 않는다
    (M3 7단계 다중 워커 실측 — 10 s 정지 뒤 살아 있는 좌석이 접속 예산을 넘겨 기권패했다)"""
    state, users = await start(games)
    a, b = worker(games, mm, fake_clock, "w-a"), worker(games, mm, fake_clock, "w-b")
    await games.mark_connected(state.game_id, users[1], owner="w-a:conn")
    await a.tick()
    await b.tick()
    fake_clock.advance(TIMEOUT + 5 * S)            # Redis 정지 — 아무도 하트비트를 남기지 못했다(store:alive 도 그대로)
    report = await b.tick()                        # 복구 직후 b 가 먼저 돈다
    assert report.outage is not None and report.dropped == []
    await a.tick()
    await passes(fake_clock, TIMEOUT // 2)
    assert (await b.tick()).dropped == []
    assert (await clocks_of(redis_client, state.game_id)).seat(2).connected


async def test_slow_recovering_worker_is_not_reaped(games, mm, fake_clock, redis_client):
    """복구 뒤 하트비트를 늦게 재개하는 워커(장애 중 걸린 명령이 socket_timeout 을 다 쓴다)도 죽었다고 보지 않는다(검토 #2 Q6)"""
    state, users = await start(games)
    a, b = worker(games, mm, fake_clock, "w-a"), worker(games, mm, fake_clock, "w-b")
    await games.mark_connected(state.game_id, users[1], owner="w-a:conn")
    await a.tick()
    await b.tick()
    fake_clock.advance(TIMEOUT + 5 * S)            # 전역 장애
    await b.tick()                                 # b 가 먼저 회복해 장애를 기록
    await passes(fake_clock, TIMEOUT + 2 * S)      # a 는 12 s 뒤에야 하트비트를 재개 — 예전 창(10 s)이면 죽은 것으로 봤다
    assert (await b.tick()).dropped == []
    await a.tick()
    assert (await clocks_of(redis_client, state.game_id)).seat(2).connected


async def test_worker_that_really_died_during_outage_is_still_reaped(games, mm, fake_clock, redis_client):
    """대조군 — 장애 뒤에도 하트비트를 남기지 않는 워커는 유예가 끝나면 처리된다"""
    state, users = await start(games)
    a, b = worker(games, mm, fake_clock, "w-a"), worker(games, mm, fake_clock, "w-b")
    await games.mark_connected(state.game_id, users[1], owner="w-a:conn")
    await a.tick()
    await b.tick()
    fake_clock.advance(TIMEOUT + 5 * S)
    await b.tick()                                 # a 는 장애 중에 죽었다 — 다시 오지 않는다
    for _ in range(8):                             # 판정 유예(타임아웃 + 2 × socket_timeout + 주기) 뒤
        await passes(fake_clock, TIMEOUT // 2)
        report = await b.tick()
        if report.dropped:
            break
    assert report.dropped == [(state.game_id, 2)]


async def test_reconnect_before_reaping_still_pays_from_the_dead_workers_last_beat(games, mm, fake_clock, redis_client):
    """크래시한 워커의 좌석이 스위퍼 처리 전에 다른 워커로 다시 붙어도, 그 워커의 마지막 하트비트부터 끊겨 있던 시간이 과금된다
    (§8 크래시 = 일반 끊김. 예전에는 소유만 옮겨 하트비트 타임아웃 안의 재접속이 무료였다)"""
    state, users = await start(games)
    dead, alive = worker(games, mm, fake_clock, "w-dead"), worker(games, mm, fake_clock, "w-alive")
    await games.mark_connected(state.game_id, users[1], owner="w-dead:c1")
    await dead.tick()
    last_beat = fake_clock.ms
    await alive.tick()
    await passes(fake_clock, TIMEOUT + 2 * S)                 # w-dead 는 SIGKILL — 스위퍼가 아직 그 좌석을 처리하기 전
    seat = (await clocks_of(redis_client, state.game_id)).seat(2)
    assert seat.connected and seat.owner == "w-dead:c1"       # 처리 전이다(이 경로를 판별한다)
    before = seat.conn_remaining_ms
    assert await games.mark_connected(state.game_id, users[1], owner="w-alive:c2")   # 재접속(이었다)
    seat = (await clocks_of(redis_client, state.game_id)).seat(2)
    assert seat.connected and seat.owner == "w-alive:c2"
    assert before - seat.conn_remaining_ms == fake_clock.ms - last_beat


async def test_moving_from_a_live_worker_is_free(games, mm, fake_clock, redis_client):
    """대조군 — 살아 있는 워커에서 다른 워커로 옮기는 교체(4000)는 끊김이 아니다"""
    state, users = await start(games)
    a, b = worker(games, mm, fake_clock, "w-a"), worker(games, mm, fake_clock, "w-b")
    await games.mark_connected(state.game_id, users[1], owner="w-a:c1")
    await a.tick()
    await b.tick()
    await passes(fake_clock, 3 * S)
    before = (await clocks_of(redis_client, state.game_id)).seat(2).conn_remaining_ms
    await games.mark_connected(state.game_id, users[1], owner="w-b:c2")
    assert (await clocks_of(redis_client, state.game_id)).seat(2).conn_remaining_ms == before


# ----- M4-1 독립 검토 — 쓰기와 통지의 원자성 (S4 kill 간헐 실패의 원인) -----

async def test_events_are_published_inside_the_commit_so_a_crash_after_writing_loses_nothing(
        redis_client, fake_clock, monkeypatch):
    """쓰기 직후·발행 전에 워커가 죽는 창 — 상태는 바뀌었는데 통지가 영영 없었다. 실제 발행자는 쓰기 Lua 안에서 PUBLISH 한다:
    커밋 직후 예외(워커 사망 흉내)가 나도 구독자는 이미 받았다"""
    import asyncio
    from app.db.redis import new_pubsub_client
    from app.services import events as events_module
    from app.services.maze_game import MazeGameService as Service

    games = Service(lambda: None, clock=fake_clock, publisher=events_module.RedisPublisher())
    state = await games.create_game(mode="duel", is_ranked=False,
                                    players=[SeatPlayer(1, 1, "a"), SeatPlayer(2, 2, "b")])
    client = new_pubsub_client("test-atomic-publish")
    pubsub = client.pubsub()
    await pubsub.subscribe(keys.events("game", state.game_id))
    await pubsub.get_message(timeout=1.0)                       # 구독 확인

    real_commit = Service._commit

    async def commit_then_die(self, *args, **kwargs):
        await real_commit(self, *args, **kwargs)
        raise SystemExit("worker killed right after the write")   # 발행 루프에 닿기 전

    monkeypatch.setattr(Service, "_commit", commit_then_die)
    target = state.get_valid_pawn_moves()[0]
    try:
        await games.move(state.game_id, 1, target.row, target.col)
    except SystemExit:
        pass
    got = None
    for _ in range(20):
        message = await pubsub.get_message(timeout=0.2)
        if message and message["type"] == "message":
            got = events_module.Event.from_json(message["data"])
            break
    await pubsub.aclose()
    await client.aclose()
    assert (await games.load_game(state.game_id)).turn_count == 1      # 쓰기는 됐다
    assert got is not None and got.kind == events_module.GAME_UPDATED   # 통지도 함께 나갔다


async def test_recording_publishers_still_receive_events_after_the_commit(redis_client, fake_clock):
    """in_commit 이 없는 발행자(테스트 기록용)는 지금처럼 쓰기 뒤에 받는다 — 테스트들이 기대는 경로"""
    pub = RecordingPublisher()
    games = MazeGameService(lambda: None, clock=fake_clock, publisher=pub)
    state = await games.create_game(mode="duel", is_ranked=False,
                                    players=[SeatPlayer(1, 1, "a"), SeatPlayer(2, 2, "b")])
    target = state.get_valid_pawn_moves()[0]
    await games.move(state.game_id, 1, target.row, target.col)
    assert any(e.kind == "game_updated" for e in pub.events)
