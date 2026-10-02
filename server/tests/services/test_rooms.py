"""
친구 대전 방 — Redis 방 상태, 방 seat_no = 게임 seat_no, 비랭크 게임 시작 (maze.md §4)

정원은 배치 테이블에서만 온다. duel·trio·quad 파라미터화로 확인한다.
"""

import itertools

import pytest

from app.db import redis_keys as keys
from app.games.maze import GameState
from app.services.activity import MultiplayerError
from app.services.maze_game import GAME
from app.services.rooms import ROOM_CODE_CHARS, ROOM_CODE_LENGTH, PLAYING, Room, Rooms


@pytest.fixture
def rooms(games_no_db) -> Rooms:
    return Rooms(games={GAME: games_no_db})


async def full_room(rooms, mode: str, seats: int) -> Room:
    room = await rooms.create_room(GAME, mode, 1, "host")
    for uid in range(2, seats + 1):
        room = await rooms.join_room(room.code, uid, f"g{uid}")
    return room


# ----- 생성·참가 -----

async def test_create_room(rooms, redis_client, seat_mode):
    mode, seats = seat_mode
    room = await rooms.create_room(GAME, mode, 1, "host")

    assert len(room.code) == ROOM_CODE_LENGTH
    assert set(room.code) <= set(ROOM_CODE_CHARS)
    assert room.capacity == seats
    assert [(p.seat_no, p.user_id, p.is_host) for p in room.players] == [(1, 1, True)]
    assert await rooms.get_room(room.code) == room
    assert await redis_client.get(keys.user_activity(1)) == keys.activity_room(room.code)
    assert await redis_client.ttl(keys.room(room.code)) > 0


async def test_room_code_collision_retries(games_no_db, redis_client):
    codes = itertools.chain(["AAAAAA", "AAAAAA"], itertools.repeat("BBBBBB"))
    rooms = Rooms(games={GAME: games_no_db}, code_factory=lambda: next(codes))
    first = await rooms.create_room(GAME, "duel", 1, "a")
    second = await rooms.create_room(GAME, "duel", 2, "b")
    assert (first.code, second.code) == ("AAAAAA", "BBBBBB")


async def test_join_up_to_capacity_then_full(rooms, seat_mode):
    mode, seats = seat_mode
    room = await full_room(rooms, mode, seats)
    assert [p.seat_no for p in room.players] == list(range(1, seats + 1))

    with pytest.raises(MultiplayerError) as exc:
        await rooms.join_room(room.code, 99, "late")
    assert exc.value.code == "room_full"


async def test_join_missing_room(rooms):
    with pytest.raises(MultiplayerError) as exc:
        await rooms.join_room("ZZZZZZ", 2, "g")
    assert exc.value.code == "room_not_found"


async def test_user_in_queue_cannot_join_room(rooms, redis_client):
    room = await rooms.create_room(GAME, "trio", 1, "host")
    await redis_client.set(keys.user_activity(2), keys.activity_queue(GAME, "trio"))
    with pytest.raises(MultiplayerError) as exc:
        await rooms.join_room(room.code, 2, "g")
    assert exc.value.code == "already_in_queue"
    assert len((await rooms.get_room(room.code)).players) == 1


async def test_host_cannot_create_second_room(rooms):
    await rooms.create_room(GAME, "duel", 1, "host")
    with pytest.raises(MultiplayerError) as exc:
        await rooms.create_room(GAME, "trio", 1, "host")
    assert exc.value.code == "already_in_room"


# ----- 이탈 -----

async def test_guest_leave_renumbers_seats(rooms, redis_client, seat_mode):
    mode, seats = seat_mode
    room = await full_room(rooms, mode, seats)

    result = await rooms.leave_room(2)
    assert not result.dissolved
    assert [p.seat_no for p in result.room.players] == list(range(1, seats))
    assert 2 not in result.room.user_ids
    assert result.notify_user_ids == result.room.user_ids
    assert await redis_client.get(keys.user_activity(2)) is None


async def test_host_leave_dissolves(rooms, redis_client, seat_mode):
    mode, seats = seat_mode
    room = await full_room(rooms, mode, seats)

    result = await rooms.leave_room(1)
    assert result.dissolved
    assert result.notify_user_ids == list(range(2, seats + 1))
    assert await rooms.get_room(room.code) is None
    for uid in range(1, seats + 1):
        assert await redis_client.get(keys.user_activity(uid)) is None


async def test_leave_without_room(rooms):
    with pytest.raises(MultiplayerError) as exc:
        await rooms.leave_room(1)
    assert exc.value.code == "not_in_room"


# ----- 시작 -----

async def test_all_ready_starts_unranked_game(rooms, games_no_db, redis_client, seat_mode):
    mode, seats = seat_mode
    room = await full_room(rooms, mode, seats)

    for uid in range(1, seats):
        assert isinstance(await rooms.set_ready(uid), Room)
    state = await rooms.set_ready(seats)
    assert isinstance(state, GameState)

    meta = await games_no_db.get_meta(state.game_id)
    assert not meta.is_ranked
    assert meta.room_code == room.code
    # 방 seat_no 가 그대로 게임 seat_no 다
    assert [(p.seat_no, p.user_id) for p in meta.players] == [
        (p.seat_no, p.user_id) for p in room.players
    ]

    started = await rooms.get_room(room.code)
    assert (started.status, started.game_id) == (PLAYING, state.game_id)
    for uid in range(1, seats + 1):
        assert await redis_client.get(keys.user_activity(uid)) == keys.activity_game(state.game_id)

    with pytest.raises(MultiplayerError) as exc:
        await rooms.join_room(room.code, 99, "late")
    assert exc.value.code == "room_full"  # 시작된 방에는 빈 좌석이 없다
    # 시작 후 방 이탈은 항복 경로다 (§9) — 방 서비스는 다루지 않는다
    with pytest.raises(MultiplayerError) as exc:
        await rooms.leave_room(1)
    assert exc.value.code == "not_in_room"


@pytest.mark.parametrize("allow", [False, True])
async def test_spectate_setting_is_copied_to_game(rooms, games_no_db, allow):
    """방 설정 allow_spectate → 게임 meta 의 불변 플래그 (maze.md §9 관전 전환)"""
    room = await rooms.create_room(GAME, "duel", 1, "host", allow_spectate=allow)
    assert room.allow_spectate is allow
    assert (await rooms.get_room(room.code)).allow_spectate is allow
    await rooms.join_room(room.code, 2, "guest")
    await rooms.set_ready(1)
    state = await rooms.set_ready(2)
    assert (await games_no_db.get_meta(state.game_id)).spectate_on_elimination is allow


async def test_spectate_defaults_off(rooms):
    room = await rooms.create_room(GAME, "duel", 1, "host")
    assert room.allow_spectate is False


async def test_ready_before_full_does_not_start(rooms):
    room = await rooms.create_room(GAME, "trio", 1, "host")
    await rooms.join_room(room.code, 2, "g")
    await rooms.set_ready(1)
    result = await rooms.set_ready(2)
    assert isinstance(result, Room)
    assert result.status == "waiting"


async def test_unranked_game_is_recorded(games, make_users, session_factory):
    from app.db.repository import GameSessionRepository

    rooms = Rooms(games={GAME: games})
    host, guest = await make_users(2)
    room = await rooms.create_room(GAME, "duel", host, "host")
    await rooms.join_room(room.code, guest, "guest")
    await rooms.set_ready(host)
    state = await rooms.set_ready(guest)

    async with session_factory() as session:
        record = await GameSessionRepository(session).get_by_id(state.game_id)
    assert record.is_ranked is False
