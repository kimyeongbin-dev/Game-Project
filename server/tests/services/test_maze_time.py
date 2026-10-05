"""
게임 서비스의 시간 체계 — 시계 저장·데드라인 색인·지연 보정·끊김 (maze.md §8·§9, M3 6단계 커밋 2)

시각은 FakeClock 으로 넘긴다 — 만료를 sleep 으로 기다리지 않는다. DB 는 쓰지 않는다.
"""

import inspect
import json

import pytest

from app.core.config import settings
from app.db import redis_keys as keys
from app.services import events
from app.services.maze_clock import GameClocks
from app.services.maze_game import GAME, GameBusy, MazeGameService, SeatPlayer

S = 1000
INITIAL = settings.clock_initial_ms
INCREMENT = settings.clock_increment_ms
BUDGET = settings.connection_budget_ms


class RecordingPublisher:
    def __init__(self):
        self.events: list[events.Event] = []

    async def publish(self, event) -> None:
        self.events.append(event)


@pytest.fixture
def pub() -> RecordingPublisher:
    return RecordingPublisher()


@pytest.fixture
def games(redis_client, pub, fake_clock) -> MazeGameService:
    return MazeGameService(lambda: None, publisher=pub, clock=fake_clock)


async def start(games, mode, seats):
    users = list(range(501, 501 + seats))
    state = await games.create_game(
        mode=mode, is_ranked=False,
        players=[SeatPlayer(i + 1, uid, f"p{uid}") for i, uid in enumerate(users)],
    )
    return state, users


async def clocks_of(redis, game_id) -> GameClocks:
    return GameClocks.from_dict(json.loads(await redis.get(keys.game_clocks(game_id))))


async def members(redis, game_id) -> dict[str, int]:
    """이 게임의 데드라인 member → score"""
    rows = await redis.zrange(keys.deadlines(GAME), 0, -1, withscores=True)
    return {m: int(score) for m, score in rows if keys.parse_deadline(m)[1] == game_id}


async def move_any(games, state_id, user_id):
    state = await games.load_game(state_id)
    target = state.get_valid_pawn_moves()[0]
    return await games.move(state_id, user_id, target.row, target.col)


# ----- 생성 -----

async def test_create_stores_clocks_and_one_clock_deadline(games, redis_client, fake_clock, seat_mode):
    mode, seats = seat_mode
    state, _ = await start(games, mode, seats)
    clocks = await clocks_of(redis_client, state.game_id)
    assert [s.seat_no for s in clocks.seats] == list(range(1, seats + 1))
    assert all(s.remaining_ms == INITIAL and s.conn_remaining_ms == BUDGET for s in clocks.seats)
    assert await redis_client.ttl(keys.game_clocks(state.game_id)) == -1
    assert await members(redis_client, state.game_id) == {
        keys.deadline_clock(state.game_id): fake_clock.ms + INITIAL,
    }


# ----- Fischer -----

async def test_accepted_move_charges_elapsed_and_adds_increment(games, redis_client, fake_clock, seat_mode):
    mode, seats = seat_mode
    state, users = await start(games, mode, seats)
    fake_clock.advance(10 * S)
    assert (await move_any(games, state.game_id, users[0])).rejection is None

    clocks = await clocks_of(redis_client, state.game_id)
    assert clocks.seat(1).remaining_ms == INITIAL - 10 * S + INCREMENT
    assert clocks.turn_started_at_ms == fake_clock.ms
    assert await members(redis_client, state.game_id) == {
        keys.deadline_clock(state.game_id): fake_clock.ms + INITIAL,   # 다음 좌석의 시계
    }


async def test_rejected_wall_leaves_clocks_and_deadline(games, redis_client, fake_clock):
    state, users = await start(games, "duel", 2)
    before_clocks = await redis_client.get(keys.game_clocks(state.game_id))
    before_due = await members(redis_client, state.game_id)
    fake_clock.advance(7 * S)
    outcome = await games.place_wall(state.game_id, users[0], 99, 99, "horizontal")
    assert outcome.rejection == "invalid_wall_position"
    assert await redis_client.get(keys.game_clocks(state.game_id)) == before_clocks
    assert await members(redis_client, state.game_id) == before_due


async def test_off_turn_action_does_not_charge_anyone(games, redis_client, fake_clock):
    state, users = await start(games, "trio", 3)
    fake_clock.advance(5 * S)
    assert (await move_any(games, state.game_id, users[1])).rejection == "not_your_turn"
    clocks = await clocks_of(redis_client, state.game_id)
    assert [s.remaining_ms for s in clocks.seats] == [INITIAL] * 3


# ----- 지연 보정 (§8 — 행동 수신 시 만료를 먼저) -----

async def test_action_after_exhaustion_forfeits_first(games, redis_client, fake_clock, pub, seat_mode):
    mode, seats = seat_mode
    state, users = await start(games, mode, seats)
    fake_clock.advance(INITIAL + 1)
    outcome = await move_any(games, state.game_id, users[0])

    assert outcome.rejection == "not_in_game"
    seat1 = outcome.state.seat(1)
    assert seat1.is_eliminated and seat1.elimination_reason == "time_forfeit"
    assert pub.events[-1].hint["last_action"] == {"seat_no": 1, "kind": "eliminated", "reason": "time_forfeit",
                                                  "survivors": seats - 1}
    due = await members(redis_client, state.game_id)
    if seats == 2:
        assert outcome.ended and due == {}
    else:
        # 다음 좌석의 시계는 처리 시각부터 — 감지 지연을 물리지 않는다
        assert outcome.state.current_seat_no == 2
        assert due == {keys.deadline_clock(state.game_id): fake_clock.ms + INITIAL}


async def test_exactly_at_deadline_is_exhausted(games, fake_clock):
    state, users = await start(games, "duel", 2)
    fake_clock.advance(INITIAL)
    assert (await games.expire(state.game_id)) == [(1, "time_forfeit")]


async def test_expire_before_deadline_does_nothing(games, redis_client, fake_clock):
    state, _ = await start(games, "duel", 2)
    fake_clock.advance(INITIAL - 1)
    assert await games.expire(state.game_id) == []
    assert not (await games.load_game(state.game_id)).seat(1).is_eliminated


async def test_expire_twice_eliminates_once(games, fake_clock, pub):
    state, _ = await start(games, "trio", 3)
    fake_clock.advance(INITIAL + S)
    assert await games.expire(state.game_id) == [(1, "time_forfeit")]
    assert await games.expire(state.game_id) == []
    eliminated = [e for e in pub.events if e.hint.get("last_action", {}).get("kind") == "eliminated"]
    assert len(eliminated) == 1


async def test_expire_rewrites_stale_score(games, redis_client, fake_clock):
    """색인 점수는 힌트다 — 과거로 틀어져 있어도 재계산이 권위이고 점수를 바로잡는다"""
    state, _ = await start(games, "duel", 2)
    member = keys.deadline_clock(state.game_id)
    await redis_client.zadd(keys.deadlines(GAME), {member: 0})
    assert await games.expire(state.game_id) == []
    assert int(await redis_client.zscore(keys.deadlines(GAME), member)) == fake_clock.ms + INITIAL


# ----- 끊김·재접속 -----

async def test_connection_clock_accumulates_without_reset(games, redis_client, fake_clock, pub):
    state, users = await start(games, "duel", 2)
    gid = state.game_id
    for gap in (10 * S, 5 * S):
        got = await games.mark_disconnected(gid, users[1])
        assert got.seat_no == 2 and got.disconnected_at_ms == fake_clock.ms
        assert keys.deadline_grace(gid, 2) in await members(redis_client, gid)
        fake_clock.advance(gap)
        assert await games.mark_connected(gid, users[1]) is True
        assert keys.deadline_grace(gid, 2) not in await members(redis_client, gid)
        fake_clock.advance(100 * S)   # 연결된 동안은 흐르지 않는다
    assert (await clocks_of(redis_client, gid)).seat(2).conn_remaining_ms == BUDGET - 15 * S
    kinds = [e.kind for e in pub.events]
    assert kinds.count(events.SEAT_DISCONNECTED) == 2 and kinds.count(events.SEAT_RECONNECTED) == 2


async def test_second_disconnect_keeps_first_start(games, fake_clock, pub):
    state, users = await start(games, "duel", 2)
    first = await games.mark_disconnected(state.game_id, users[1])
    fake_clock.advance(4 * S)
    again = await games.mark_disconnected(state.game_id, users[1])
    assert again.disconnected_at_ms == first.disconnected_at_ms
    assert again.grace_remaining_ms == BUDGET - 4 * S
    assert [e.kind for e in pub.events].count(events.SEAT_DISCONNECTED) == 1


async def test_connected_seat_reconnect_is_noop(games):
    state, users = await start(games, "duel", 2)
    assert await games.mark_connected(state.game_id, users[1]) is False


async def test_connection_exhaustion_forfeits(games, redis_client, fake_clock, seat_mode):
    mode, seats = seat_mode
    state, users = await start(games, mode, seats)
    await games.mark_disconnected(state.game_id, users[-1])
    fake_clock.advance(BUDGET)
    assert await games.expire(state.game_id) == [(seats, "disconnect_forfeit")]
    after = await games.load_game(state.game_id)
    assert after.seat(seats).is_eliminated
    assert keys.deadline_grace(state.game_id, seats) not in await members(redis_client, state.game_id)


async def test_disconnected_on_own_turn_loses_both(games, redis_client, fake_clock):
    state, users = await start(games, "duel", 2)
    await games.mark_disconnected(state.game_id, users[0])
    fake_clock.advance(20 * S)
    clocks = await clocks_of(redis_client, state.game_id)
    assert clocks.game_remaining(1, 1, fake_clock.ms) == INITIAL - 20 * S
    assert clocks.conn_remaining(1, fake_clock.ms) == BUDGET - 20 * S
    # 접속 시계가 먼저 0 이 된다 — 끊긴 채 생각할 수 없다
    fake_clock.advance(BUDGET)
    assert await games.expire(state.game_id) == [(1, "disconnect_forfeit")]


async def test_action_counts_as_reconnect(games, redis_client, fake_clock, pub):
    state, users = await start(games, "duel", 2)
    await games.mark_disconnected(state.game_id, users[0])
    fake_clock.advance(3 * S)
    assert (await move_any(games, state.game_id, users[0])).rejection is None
    clocks = await clocks_of(redis_client, state.game_id)
    assert clocks.seat(1).connected and clocks.seat(1).conn_remaining_ms == BUDGET - 3 * S
    assert events.SEAT_RECONNECTED in [e.kind for e in pub.events]


async def test_eliminated_or_outsider_cannot_disconnect(games, fake_clock):
    state, users = await start(games, "trio", 3)
    await games.surrender(state.game_id, users[2])
    assert await games.mark_disconnected(state.game_id, users[2]) is None
    assert await games.mark_disconnected(state.game_id, 999) is None


# ----- 탈락 (§9 탈락 처리 3·5·7번) -----

async def test_current_seat_elimination_hands_turn_with_fresh_deadline(games, redis_client, fake_clock, seat_mode):
    mode, seats = seat_mode
    state, users = await start(games, mode, seats)
    await games.mark_disconnected(state.game_id, users[0])
    fake_clock.advance(30 * S)
    outcome = await games.surrender(state.game_id, users[0])
    due = await members(redis_client, state.game_id)
    if seats == 2:
        assert outcome.ended and due == {}
        return
    assert outcome.state.current_seat_no == 2
    # 탈락 좌석의 grace 는 사라지고, 다음 좌석 시계는 지금부터
    assert due == {keys.deadline_clock(state.game_id): fake_clock.ms + INITIAL}
    frozen = (await clocks_of(redis_client, state.game_id)).seat(1)
    assert frozen.frozen and frozen.remaining_ms == INITIAL - 30 * S   # 증분 없음


async def test_time_forfeited_seat_vision_stays_frozen(games, redis_client, fake_clock, seat_mode):
    """5단계 동결 — 시간패 이후 남의 행동이 탈락 좌석의 발견 맵을 바꾸지 않는다"""
    mode, seats = seat_mode
    if seats == 2:
        pytest.skip("2인전은 시간패로 바로 끝난다")
    state, users = await start(games, mode, seats)
    fake_clock.advance(INITIAL + S)
    assert await games.expire(state.game_id) == [(1, "time_forfeit")]
    frozen = await redis_client.get(keys.game_vision(state.game_id, 1))
    for uid in users[1:]:
        assert (await move_any(games, state.game_id, uid)).rejection is None
    assert await redis_client.get(keys.game_vision(state.game_id, 1)) == frozen


async def test_finished_game_clears_deadlines_and_expires_clocks(games, redis_client, fake_clock):
    state, users = await start(games, "duel", 2)
    await games.mark_disconnected(state.game_id, users[1])
    await games.surrender(state.game_id, users[0])
    assert await members(redis_client, state.game_id) == {}
    ttl = await redis_client.ttl(keys.game_clocks(state.game_id))
    assert abs(ttl - await redis_client.ttl(keys.game_state(state.game_id))) <= 1 and ttl > 0
    assert (await clocks_of(redis_client, state.game_id)).stopped


async def test_server_elimination_of_eliminated_seat_is_rejected(games):
    state, users = await start(games, "trio", 3)
    await games.surrender(state.game_id, users[1])
    assert (await games.eliminate(state.game_id, 2, "time_forfeit")).rejection == "not_in_game"


# ----- 원자성 -----

async def test_lost_lock_writes_no_clocks_or_deadlines(games, redis_client, fake_clock, monkeypatch):
    state, users = await start(games, "trio", 3)
    gid = state.game_id
    before = (await redis_client.get(keys.game_clocks(gid)), await members(redis_client, gid))
    observe_all = MazeGameService._observe_all

    async def steal_lock(self, redis, s):
        out = await observe_all(self, redis, s)
        await redis.set(keys.game_lock(gid), "someone-else")
        return out

    monkeypatch.setattr(MazeGameService, "_observe_all", steal_lock)
    fake_clock.advance(10 * S)
    with pytest.raises(GameBusy):
        await move_any(games, gid, users[0])
    assert (await redis_client.get(keys.game_clocks(gid)), await members(redis_client, gid)) == before
    await redis_client.delete(keys.game_lock(gid))


# ----- 조작 경로 -----

def test_client_facing_methods_take_no_time_or_seat():
    """시각은 서버가 읽고, 좌석은 인증된 user_id 로 정한다. seat 를 받는 것은 서버 행위뿐"""
    client_facing = ["move", "place_wall", "surrender", "mark_disconnected", "mark_connected"]
    for name in client_facing:
        params = set(inspect.signature(getattr(MazeGameService, name)).parameters)
        assert not params & {"now", "now_ms", "at", "at_ms", "timestamp", "seat_no", "elapsed_ms"}, name
        assert "user_id" in params, name
    for name in dir(MazeGameService):
        if name.startswith("_") or not callable(getattr(MazeGameService, name)):
            continue
        params = set(inspect.signature(getattr(MazeGameService, name)).parameters)
        assert not params & {"now", "now_ms", "timestamp", "elapsed_ms"}, name
