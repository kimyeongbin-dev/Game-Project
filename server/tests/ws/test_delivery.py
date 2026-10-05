"""
내부 이벤트 → 수신자별 §12 메시지 (M3 7단계 판단 1·2·3)

서비스가 발행한 이벤트를 기록해 두었다가 수신자마다 `Delivery.deliver` 로 바꾼다 — 버스 없이 결정적으로.
실제 Redis(논리 DB 1), DB 없음. 버스 경유 전달은 tests/ws/test_bus.py.
"""

import random

import pytest

from app.games.maze import GameState
from app.services.matchmaking import READY_DEADLINE_SEC, Matchmaking
from app.services.maze_game import GAME, MazeGameService, SeatPlayer
from app.services.rooms import Rooms
from app.ws.delivery import Delivery
from tests.services.test_events import RecordingPublisher


def keys_in(obj) -> set[str]:
    found = set()
    if isinstance(obj, dict):
        found |= obj.keys()
        for v in obj.values():
            found |= keys_in(v)
    elif isinstance(obj, list):
        for v in obj:
            found |= keys_in(v)
    return found


@pytest.fixture
def pub() -> RecordingPublisher:
    return RecordingPublisher()


@pytest.fixture
def games(redis_client, pub, fake_clock) -> MazeGameService:
    return MazeGameService(lambda: None, publisher=pub, clock=fake_clock)


@pytest.fixture
def delivery(games, pub, fake_clock) -> Delivery:
    rooms = Rooms(games={GAME: games}, publisher=pub)
    mm = Matchmaking(games={GAME: games}, rng_factory=lambda: random.Random(1), publisher=pub, clock=fake_clock)
    return Delivery(games, rooms, mm, clock=fake_clock)


async def start(games, mode: str, seats: int):
    users = list(range(201, 201 + seats))
    state = await games.create_game(
        mode=mode, is_ranked=False,
        players=[SeatPlayer(i + 1, uid, f"p{uid}") for i, uid in enumerate(users)],
    )
    return state, users


async def drain(pub: RecordingPublisher, delivery: Delivery) -> dict[int, list[dict]]:
    """기록된 이벤트를 수신자별 메시지로 — 그리고 비운다"""
    out: dict[int, list[dict]] = {}
    for event in pub.events:
        for uid in event.recipients:
            out.setdefault(uid, []).extend(await delivery.deliver(event, uid))
    pub.events.clear()
    return out


def types(messages) -> list[str]:
    return [m["type"] for m in messages]


# ----- 게임 -----

async def test_game_start_per_seat(games, pub, delivery, seat_mode):
    mode, seats = seat_mode
    _, users = await start(games, mode, seats)
    got = await drain(pub, delivery)
    for seat_no, uid in enumerate(users, start=1):
        msgs = got[uid]
        assert types(msgs) == ["game_start", "game_state", "turn_change"]
        assert msgs[0]["payload"]["my_seat_no"] == seat_no
        assert msgs[1]["payload"]["me"]["seat_no"] == seat_no
        assert msgs[2]["payload"]["last_action"] is None and msgs[2]["payload"]["current_seat_no"] == 1
        assert {m["version"] for m in msgs} == {1}
        assert not {"spectator", "full_board", "user_id"} & keys_in(msgs)


async def test_play_to_end_full_board_only_in_game_end(games, pub, delivery, seat_mode):
    """종료 전 어떤 메시지에도 full_board 가 없고, 종료는 전원에게 game_end 한 번 (§10)"""
    mode, seats = seat_mode
    state, users = await start(games, mode, seats)
    target = state.get_valid_pawn_moves()[0]
    await games.move(state.game_id, users[0], target.row, target.col)
    before_end = await drain(pub, delivery)
    for uid in users:
        assert types(before_end[uid])[-2:] == ["game_state", "turn_change"]
        assert before_end[uid][-1]["payload"]["last_action"] == {"seat_no": 1, "kind": "move"}

    for uid in users[1:]:    # 1번만 남기고 전원 항복 → last_standing
        await games.surrender(state.game_id, uid)
    tail = await drain(pub, delivery)

    everything = [m for uid in users for m in before_end[uid] + tail[uid]]
    ends = [m for m in everything if m["type"] == "game_end"]
    assert len(ends) == len(users)                       # 전원 한 번씩
    assert all("full_board" not in keys_in(m) for m in everything if m["type"] != "game_end")
    for uid in users:
        lefts = [m["payload"] for m in tail[uid] if m["type"] == "player_left"]
        assert [p["seat_no"] for p in lefts] == list(range(2, seats + 1))
        assert all(p["state"] == "eliminated" and p["reason"] == "surrender" for p in lefts)
        assert [p["survivors"] for p in lefts] == list(range(seats - 1, 0, -1))
        assert tail[uid][-1]["type"] == "game_end"
        end = tail[uid][-1]["payload"]
        assert end["reason"] == "last_standing" and end["full_board"]["final_positions"]
        assert "turn_change" not in types(tail[uid][-2:])  # 끝난 뒤에는 차례가 없다
    assert "user_id" not in keys_in(everything)


async def test_version_strictly_increases_across_kinds(games, pub, delivery, fake_clock, seat_mode):
    """행동·끊김·재접속·탈락·종료가 섞여도 게임 이벤트 번호는 엄격 증가 (검토 L23)"""
    mode, seats = seat_mode
    state, users = await start(games, mode, seats)
    gid = state.game_id
    target = state.get_valid_pawn_moves()[0]
    await games.move(gid, users[0], target.row, target.col)
    await games.mark_disconnected(gid, users[-1])
    fake_clock.advance(1_000)
    await games.mark_connected(gid, users[-1])
    await games.mark_disconnected(gid, users[-1])       # 끊김·재접속이 같은 turn_count 에서 반복
    await games.mark_connected(gid, users[-1])
    for uid in users[1:]:
        await games.surrender(gid, uid)

    seqs = [e.seq for e in pub.events]
    assert seqs == list(range(1, len(seqs) + 1))
    resync = await delivery.game_resync(gid, users[0])
    assert {m["version"] for m in resync} == {seqs[-1]}
    assert types(resync) == ["game_state", "game_end"]   # 끝난 게임의 재동기화는 결과까지


async def test_disconnect_and_reconnect_wire(games, pub, delivery, seat_mode):
    mode, seats = seat_mode
    state, users = await start(games, mode, seats)
    pub.events.clear()
    await games.mark_disconnected(state.game_id, users[-1])
    await games.mark_connected(state.game_id, users[-1])
    got = await drain(pub, delivery)
    for uid in users[:-1]:
        left, back = got[uid]
        assert left["type"] == "player_left" and left["payload"]["state"] == "reconnecting"
        assert left["payload"]["seat_no"] == seats and left["payload"]["reason"] is None
        assert left["payload"]["grace_remaining_ms"] > 0 and left["payload"]["survivors"] == seats
        assert back == {"type": "player_joined", "version": back["version"],
                        "payload": {"seat_no": seats, "state": "reconnected"}}


async def test_spectator_only_for_eliminated_in_friend_room(games, pub, delivery):
    state = await games.create_game(
        mode="trio", is_ranked=False, spectate_on_elimination=True,
        players=[SeatPlayer(i, 300 + i, f"s{i}") for i in (1, 2, 3)],
    )
    pub.events.clear()
    await games.surrender(state.game_id, 303)
    got = await drain(pub, delivery)
    state_of = {uid: next(m for m in got[uid] if m["type"] == "game_state") for uid in (301, 302, 303)}
    assert "spectator" in state_of[303]["payload"]
    assert "spectator" not in state_of[301]["payload"] and "spectator" not in state_of[302]["payload"]


async def test_lost_state_void_is_game_end_without_board(games, pub, delivery, redis_client):
    from app.db import redis_keys as keys

    state, users = await start(games, "duel", 2)
    await redis_client.delete(keys.game_state(state.game_id))
    pub.events.clear()
    assert await games.void_lost_game(state.game_id)  # DB 가 없어도 남은 meta 를 지운 쪽이 통지한다
    got = await drain(pub, delivery)
    for uid in users:
        [end] = got[uid]
        assert end["type"] == "game_end" and end["payload"]["reason"] == "server_fault"
        assert end["payload"]["full_board"] is None


async def test_long_outage_void_keeps_board(games, pub, delivery, fake_clock):
    state, users = await start(games, "trio", 3)
    pub.events.clear()
    assert await games.void_game(state.game_id, started_before_ms=fake_clock.ms)
    got = await drain(pub, delivery)
    for uid in users:
        [end] = got[uid]
        assert end["payload"]["reason"] == "server_fault"
        assert {r["result"] for r in end["payload"]["results"]} == {"void"}
        assert end["payload"]["full_board"] is not None


# ----- 방·매치 -----

async def test_room_events_skip_actor_and_hide_user_ids(games, pub, delivery):
    rooms = delivery._rooms
    room = await rooms.create_room(GAME, "trio", 1, "host")
    await rooms.join_room(room.code, 2, "g2")
    await rooms.join_room(room.code, 3, "g3")
    await rooms.set_ready(2)
    await rooms.update_settings(1, "trio", True)
    await rooms.leave_room(3)
    got = await drain(pub, delivery)

    assert types(got[1]) == ["player_joined", "player_joined", "player_ready", "player_left"]
    assert types(got[2]) == ["player_joined", "room_joined", "player_left"]          # 자기 참가·준비는 없다
    assert types(got[3]) == ["player_ready", "room_joined"]                          # 자기 퇴장도 없다
    assert got[2][1]["payload"]["allow_spectate"] is True
    assert got[1][3]["payload"]["seat_no"] == 3
    assert "user_id" not in keys_in(got)


async def test_settings_change_rules(games, delivery):
    from app.services.activity import MultiplayerError

    rooms = delivery._rooms
    room = await rooms.create_room(GAME, "duel", 1, "host")
    await rooms.join_room(room.code, 2, "g")
    with pytest.raises(MultiplayerError, match="already_in_room"):
        await rooms.update_settings(2, "duel", True)       # 방장이 아니다
    with pytest.raises(MultiplayerError, match="already_in_room"):
        await rooms.update_settings(1, "trio", True)       # 모드는 못 바꾼다
    await rooms.set_ready(1)
    await rooms.set_ready(2)                               # 시작 — 활동이 game 으로
    with pytest.raises(MultiplayerError, match="not_in_room"):
        await rooms.update_settings(1, "duel", True)


async def test_match_messages(games, pub, delivery, fake_clock):
    mm = delivery._matches
    for uid in (11, 12):
        result = await mm.join(GAME, "duel", uid, f"n{uid}", 1000)
    got = await drain(pub, delivery)
    for uid in (11, 12):
        [matched] = got[uid]
        assert matched["type"] == "matched"
        assert matched["payload"]["ready_deadline_sec"] == READY_DEADLINE_SEC
        assert {p["mmr"] for p in matched["payload"]["players"]} == {1000}

    await mm.mark_ready(result.match.match_id, 11)
    fake_clock.advance(READY_DEADLINE_SEC * 1000)
    await mm.expire_match(result.match.match_id)
    got = await drain(pub, delivery)
    assert types(got[12]) == ["player_ready", "queue_status"]
    assert got[11][-1]["payload"]["requeued"] is True and got[11][-1]["payload"]["position"] == 1
    assert got[12][-1]["payload"] == {"mode": "duel", "position": 0, "waiting_count": 0, "requeued": False}
    assert "user_id" not in keys_in(got)
