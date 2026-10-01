"""
이벤트 발행 — 서비스 결과가 어떤 이벤트로 나가는가 (M3 4단계 판단 2·3)

기록용 publisher 를 주입해 kind·scope·recipients·hint 를 본다. DB 는 쓰지 않는다.
전달(구독·소켓)은 tests/ws/test_bus.py 몫이다.
"""

import random

import pytest

from app.db import redis_keys as keys
from app.services import events
from app.services.events import Event, RedisPublisher
from app.services.matchmaking import Matchmaking
from app.services.maze_game import GAME, MazeGameService, SeatPlayer
from app.services.rooms import Rooms

# hint 에 있으면 §6 위반인 키 — 좌표·벽·게임 상태
FORBIDDEN_HINT_KEYS = {"position", "row", "col", "walls", "board", "state", "goals"}


class RecordingPublisher:
    def __init__(self):
        self.events: list[Event] = []

    async def publish(self, event: Event) -> None:
        self.events.append(event)

    def kinds(self) -> list[str]:
        return [e.kind for e in self.events]


def assert_public(hint):
    """hint 어디에도 좌표·벽·상태 키가 없다"""
    if isinstance(hint, dict):
        assert not FORBIDDEN_HINT_KEYS & hint.keys(), hint
        for value in hint.values():
            assert_public(value)
    elif isinstance(hint, list):
        for value in hint:
            assert_public(value)


@pytest.fixture
def pub() -> RecordingPublisher:
    return RecordingPublisher()


@pytest.fixture
def games(redis_client, pub) -> MazeGameService:
    return MazeGameService(lambda: None, publisher=pub)


async def start(games, mode: str, seats: int):
    users = list(range(101, 101 + seats))
    state = await games.create_game(
        mode=mode, is_ranked=False,
        players=[SeatPlayer(i + 1, uid, f"p{uid}") for i, uid in enumerate(users)],
    )
    return state, users


# ----- 봉투 -----

def test_event_json_roundtrip():
    e = Event("game_updated", "game", "g1", (1, 2), {"last_action": {"seat_no": 1, "kind": "move"}}, 3)
    assert Event.from_json(e.to_json()) == e
    assert e.channel == keys.game_events("g1")
    assert e.channel.startswith(keys.channel_namespace())


def test_test_channels_are_explicitly_separated():
    """채널은 DB 전역이다 — 테스트는 명시 네임스페이스 "test", 앱은 "app" """
    assert keys.channel_namespace() == "test:"
    assert keys.room_events("ABC") == "test:room:ABC:events"
    assert keys.event_patterns() == ("test:game:*:events", "test:match:*:events", "test:room:*:events")
    with pytest.raises(ValueError):
        keys.events("user", "1")


def test_namespace_settings_guard():
    """기본은 앱 네임스페이스, production 은 테스트 네임스페이스를 거부한다"""
    from pydantic import ValidationError

    from app.core.config import Settings

    assert Settings(_env_file=None, pubsub_namespace="app").pubsub_namespace == "app"
    with pytest.raises(ValidationError):
        Settings(_env_file=None, environment="production", pubsub_namespace="test")
    with pytest.raises(ValidationError):
        Settings(_env_file=None, pubsub_namespace="Bad Name:")


# ----- 게임 -----

async def test_game_started(games, pub, seat_mode):
    mode, seats = seat_mode
    state, users = await start(games, mode, seats)

    [e] = pub.events
    assert (e.kind, e.scope, e.scope_id) == (events.GAME_STARTED, "game", state.game_id)
    assert e.recipients == tuple(users)
    assert [p["seat_no"] for p in e.hint["players"]] == list(range(1, seats + 1))
    assert_public(e.hint)


async def test_move_publishes_last_action_without_coordinates(games, pub, seat_mode):
    mode, seats = seat_mode
    state, users = await start(games, mode, seats)
    target = state.get_valid_pawn_moves()[0]

    await games.move(state.game_id, users[0], target.row, target.col)

    e = pub.events[-1]
    assert e.kind == events.GAME_UPDATED
    assert e.recipients == tuple(users)
    assert e.hint == {"last_action": {"seat_no": 1, "kind": "move"}, "ended": False}
    assert e.seq == 1
    assert_public(e.hint)


async def test_wall_publishes_kind_wall(games, pub):
    state, users = await start(games, "duel", 2)
    await games.place_wall(state.game_id, users[0], 3, 3, "horizontal")
    assert pub.events[-1].hint["last_action"] == {"seat_no": 1, "kind": "wall"}


async def test_rejections_are_not_published(games, pub, seat_mode):
    """거절은 행동한 사람에게만 응답한다 — 남에게 알리지 않는다"""
    mode, seats = seat_mode
    state, users = await start(games, mode, seats)
    target = state.get_valid_pawn_moves()[0]
    before = len(pub.events)

    assert (await games.move(state.game_id, users[1], target.row, target.col)).rejection == "not_your_turn"
    assert (await games.move(state.game_id, 999, target.row, target.col)).rejection == "not_in_game"
    await games.place_wall(state.game_id, users[0], 3, 3, "horizontal")
    assert (await games.place_wall(state.game_id, users[1], 3, 3, "horizontal")).rejection

    assert len(pub.events) == before + 1  # 수락된 첫 벽만


async def test_surrender_and_end(games, pub, seat_mode):
    mode, seats = seat_mode
    state, users = await start(games, mode, seats)

    await games.surrender(state.game_id, users[-1])
    e = pub.events[-1]
    assert e.hint["last_action"] == {"seat_no": seats, "kind": "eliminated", "reason": "surrender"}
    assert e.hint["ended"] is (seats == 2)
    # 탈락한 좌석도 결과를 받아야 한다 — 수신자는 meta 의 사람 좌석 전원
    assert e.recipients == tuple(users)


async def test_server_elimination_names_the_seat(games, pub):
    state, users = await start(games, "trio", 3)
    await games.eliminate(state.game_id, 2, "time_forfeit")
    assert pub.events[-1].hint["last_action"] == {"seat_no": 2, "kind": "eliminated", "reason": "time_forfeit"}


async def test_void_publishes(games, pub):
    state, users = await start(games, "duel", 2)
    await games.void_lost_game(state.game_id)
    assert pub.events[-1].kind == events.GAME_VOIDED
    assert pub.events[-1].recipients == tuple(users)


async def test_publish_failure_does_not_fail_action(redis_client, monkeypatch):
    """발행이 실패해도 상태는 이미 기록됐다 — 행동은 성공한다"""
    from redis.exceptions import ConnectionError as RedisConnectionError

    async def broken(*args, **kwargs):
        raise RedisConnectionError("pubsub down")

    monkeypatch.setattr(redis_client, "publish", broken)
    games = MazeGameService(lambda: None, publisher=RedisPublisher())
    state, users = await start(games, "duel", 2)
    target = state.get_valid_pawn_moves()[0]

    outcome = await games.move(state.game_id, users[0], target.row, target.col)
    assert outcome.rejection is None
    assert (await games.load_game(state.game_id)).turn_count == 1


# ----- 매치 -----

@pytest.fixture
def mm(games, pub) -> Matchmaking:
    return Matchmaking(games={GAME: games}, rng_factory=lambda: random.Random(7), publisher=pub)


async def test_matched_reaches_every_seat(mm, pub, seat_mode):
    mode, seats = seat_mode
    users = list(range(1, seats + 1))
    for uid in users:
        result = await mm.join(GAME, mode, uid, f"n{uid}", 1000)

    [e] = [e for e in pub.events if e.kind == events.MATCHED]
    assert e.scope == "match" and e.scope_id == result.match.match_id
    assert sorted(e.recipients) == users
    assert sorted(p["seat_no"] for p in e.hint["players"]) == list(range(1, seats + 1))
    assert_public(e.hint)


async def test_ready_then_game_started_once(mm, pub, seat_mode):
    mode, seats = seat_mode
    users = list(range(1, seats + 1))
    for uid in users:
        result = await mm.join(GAME, mode, uid, f"n{uid}", 1000)
    match_id = result.match.match_id

    for uid in users:
        await mm.mark_ready(match_id, uid)

    assert pub.kinds().count(events.MATCH_READY) == seats - 1
    assert pub.kinds().count(events.GAME_STARTED) == 1
    assert pub.kinds()[-1] == events.GAME_STARTED


async def test_expire_notifies_requeued_and_dropped(mm, pub):
    users = [1, 2]
    for uid in users:
        result = await mm.join(GAME, "duel", uid, f"n{uid}", 1000)
    await mm.mark_ready(result.match.match_id, 1)

    await mm.expire_match(result.match.match_id)
    e = pub.events[-1]
    assert e.kind == events.MATCH_EXPIRED
    assert e.hint == {"requeued": [1], "dropped": [2]}
    assert sorted(e.recipients) == users


# ----- 방 -----

@pytest.fixture
def rooms(games, pub) -> Rooms:
    return Rooms(games={GAME: games}, publisher=pub)


async def test_room_lifecycle_events(rooms, pub, seat_mode):
    mode, seats = seat_mode
    room = await rooms.create_room(GAME, mode, 1, "host")
    for uid in range(2, seats + 1):
        room = await rooms.join_room(room.code, uid, f"g{uid}")

    updates = [e for e in pub.events if e.kind == events.ROOM_UPDATED]
    assert len(updates) == seats
    assert updates[-1].recipients == tuple(range(1, seats + 1))
    assert updates[-1].hint["room"]["code"] == room.code
    assert_public(updates[-1].hint)

    for uid in range(1, seats + 1):
        await rooms.set_ready(uid)
    assert pub.kinds().count(events.ROOM_UPDATED) == seats + seats - 1
    assert pub.kinds()[-1] == events.GAME_STARTED


async def test_guest_leave_notifies_leaver_too(rooms, pub):
    room = await rooms.create_room(GAME, "trio", 1, "host")
    await rooms.join_room(room.code, 2, "g2")
    await rooms.join_room(room.code, 3, "g3")

    await rooms.leave_room(2)
    e = pub.events[-1]
    assert e.kind == events.ROOM_UPDATED
    assert set(e.recipients) == {1, 2, 3}
    assert [p["user_id"] for p in e.hint["room"]["players"]] == [1, 3]


async def test_host_leave_dissolves(rooms, pub):
    room = await rooms.create_room(GAME, "trio", 1, "host")
    await rooms.join_room(room.code, 2, "g2")

    await rooms.leave_room(1)
    e = pub.events[-1]
    assert (e.kind, e.scope_id, e.recipients) == (events.ROOM_DISSOLVED, room.code, (2,))
