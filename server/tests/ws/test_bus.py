"""
구독 버스 — 워커 간 전달, 좌석별 내용, 끊김 → 재구독 → 재동기화 (M3 4단계 판단 5)

한 프로세스 안에 EventBus 2개를 각자의 ConnectionManager·구독 연결로 띄워 **워커 2개**를
흉내 낸다. 발행은 실제 서비스가 하고(RedisPublisher), 소켓은 보낸 것을 기록하는 가짜다.
DB 는 쓰지 않는다.
"""

import asyncio
import random

import pytest
import pytest_asyncio

from app.db import redis_keys as keys
from app.services import events
from app.services.events import Event
from app.services.matchmaking import Matchmaking
from app.services.maze_game import GAME, MazeGameService, SeatPlayer
from app.services.rooms import Rooms
from app.ws.bus import CLIENT_NAME_PREFIX, EventBus
from app.ws.connection_manager import ConnectionManager
from app.ws.delivery import GAME_STATE, QUEUE_STATUS, Delivery
from tests.ws.conftest import MockWebSocket

WAIT_SEC = 2.0


async def eventually(predicate, timeout: float = WAIT_SEC):
    """조건이 참이 될 때까지 짧게 폴링한다. 시간 안에 안 되면 실패"""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while not predicate():
        if loop.time() > deadline:
            raise AssertionError("condition not met in time")
        await asyncio.sleep(0.01)


def types(ws: MockWebSocket) -> list[str]:
    return [m["type"] for m in ws.sent_messages]


def positions_in(obj) -> list[dict]:
    found = []
    if isinstance(obj, dict):
        if {"row", "col"} <= obj.keys():
            found.append({"row": obj["row"], "col": obj["col"]})
        for v in obj.values():
            found += positions_in(v)
    elif isinstance(obj, list):
        for v in obj:
            found += positions_in(v)
    return found


@pytest.fixture
def games(redis_client) -> MazeGameService:
    return MazeGameService(lambda: None)  # 기본 publisher = 실제 Redis 발행


@pytest.fixture
def rooms(games) -> Rooms:
    return Rooms(games={GAME: games})


@pytest.fixture
def mm(games) -> Matchmaking:
    return Matchmaking(games={GAME: games}, rng_factory=lambda: random.Random(3))


@pytest.fixture
def delivery(games, rooms, mm) -> Delivery:
    return Delivery(games, rooms, mm)


@pytest_asyncio.fixture
async def workers(redis_client, delivery):
    """워커 2개 — (manager, bus) 쌍 둘"""
    pairs = [(m := ConnectionManager(), EventBus(m, delivery)) for _ in range(2)]
    for _, bus in pairs:
        await bus.start()
        assert bus.subscribed
    yield pairs
    for _, bus in pairs:
        await bus.stop()


async def connect(manager: ConnectionManager, user_id: int) -> MockWebSocket:
    ws = MockWebSocket()
    await manager.connect(ws, user_id, f"n{user_id}")
    return ws


async def start_game(games, mode: str, users: list[int]):
    return await games.create_game(
        mode=mode, is_ranked=False,
        players=[SeatPlayer(i + 1, uid, f"n{uid}") for i, uid in enumerate(users)],
    )


# ----- 전달 -----

async def test_cross_worker_delivery_per_seat(workers, games, seat_mode):
    """좌석을 두 워커에 번갈아 붙인다 — 양쪽 다 자기 로컬 유저에게만, 좌석별 내용으로 보낸다"""
    mode, seats = seat_mode
    users = list(range(1, seats + 1))
    sockets = {uid: await connect(workers[i % 2][0], uid) for i, uid in enumerate(users)}

    state = await start_game(games, mode, users)
    await eventually(lambda: all(GAME_STATE in types(ws) for ws in sockets.values()))

    target = state.get_valid_pawn_moves()[0]
    await games.move(state.game_id, users[0], target.row, target.col)
    await eventually(lambda: all(types(ws).count(GAME_STATE) == 2 for ws in sockets.values()))

    for seat_no, uid in enumerate(users, start=1):
        sent = sockets[uid].sent_messages
        assert types(sockets[uid]) == [
            events.GAME_STARTED, GAME_STATE, events.GAME_UPDATED, GAME_STATE
        ]
        assert sent[0]["payload"]["my_seat_no"] == seat_no
        assert sent[2]["payload"]["last_action"] == {"seat_no": 1, "kind": "move"}
        view = sent[3]["payload"]
        assert view["me"]["seat_no"] == seat_no and view["turn_count"] == 1
        # §6 — 시작 배치에서는 서로 3×3 밖이라 남의 좌표가 어디에도 없다 (변 좌표는 칸 기준이라 제외)
        assert view["visible_players"] == [] and view["last_seen_players"] == []
        no_edges = {k: v for k, v in view.items() if not k.endswith("_edges")}
        assert positions_in(no_edges) == [view["me"]["position"]]
        assert positions_in(sent[2]["payload"]) == []


async def test_non_recipients_receive_nothing(workers, games):
    manager, _ = workers[0]
    outsider = await connect(manager, 999)
    await connect(manager, 1)
    await connect(workers[1][0], 2)

    await start_game(games, "duel", [1, 2])
    await eventually(lambda: GAME_STATE in types(manager.get_connection(1).websocket))
    await asyncio.sleep(0.05)
    assert outsider.sent_messages == []


async def test_app_channels_do_not_reach_test_bus(workers, redis_client):
    """채널은 DB 전역이다 — 앱("app:") 이벤트가 테스트 버스("test:")로 오지 않는다"""
    ws = await connect(workers[0][0], 1)
    foreign = Event(events.ROOM_UPDATED, "room", "ZZZZZZ", (1,), {"room": {}})
    await redis_client.publish("app:room:ZZZZZZ:events", foreign.to_json())

    mine = Event(events.ROOM_DISSOLVED, "room", "AAAAAA", (1,), {"code": "AAAAAA"})
    await redis_client.publish(mine.channel, mine.to_json())

    await eventually(lambda: ws.sent_messages)
    assert types(ws) == [events.ROOM_DISSOLVED]


async def test_broken_message_does_not_kill_loop(workers, redis_client):
    ws = await connect(workers[0][0], 1)
    await redis_client.publish(keys.room_events("BROKEN"), "not json {")
    ok = Event(events.ROOM_DISSOLVED, "room", "OKOKOK", (1,), {"code": "OKOKOK"})
    await redis_client.publish(ok.channel, ok.to_json())

    await eventually(lambda: ws.sent_messages)
    assert types(ws) == [events.ROOM_DISSOLVED]


async def test_room_and_match_events_cross_workers(workers, rooms, mm):
    a, b = workers[0][0], workers[1][0]
    host, guest = await connect(a, 1), await connect(b, 2)

    room = await rooms.create_room(GAME, "duel", 1, "host")
    await rooms.join_room(room.code, 2, "guest")
    await eventually(lambda: types(host) == [events.ROOM_UPDATED, events.ROOM_UPDATED])
    await eventually(lambda: types(guest) == [events.ROOM_UPDATED])
    await rooms.leave_room(1)  # 호스트 → 해산
    await eventually(lambda: types(guest)[-1:] == [events.ROOM_DISSOLVED])

    for uid in (3, 4):
        await connect(a if uid == 3 else b, uid)
        result = await mm.join(GAME, "duel", uid, f"n{uid}", 1000)
    ws3, ws4 = a.get_connection(3).websocket, b.get_connection(4).websocket
    await eventually(lambda: types(ws3) == [events.MATCHED] and types(ws4) == [events.MATCHED])
    seats = {ws3.sent_messages[0]["payload"]["my_seat_no"], ws4.sent_messages[0]["payload"]["my_seat_no"]}
    assert seats == {1, 2}
    assert result.match is not None


# ----- 끊김 → 재구독 → 재동기화 -----

async def kill_bus_connection(redis_client, bus: EventBus) -> None:
    """그 버스의 구독 연결만 죽인다 — TYPE pubsub 로 서버 전체를 죽이지 않는다"""
    clients = [c for c in await redis_client.client_list() if c.get("name") == bus.name]
    assert len(clients) == 1
    await redis_client.client_kill_filter(_id=clients[0]["id"])


async def test_resubscribe_then_resync(workers, games, redis_client):
    manager, bus = workers[0]
    ws1, ws2 = await connect(manager, 1), await connect(manager, 2)
    state = await start_game(games, "duel", [1, 2])
    await eventually(lambda: GAME_STATE in types(ws1) and GAME_STATE in types(ws2))
    ws1.sent_messages.clear()
    ws2.sent_messages.clear()

    await kill_bus_connection(redis_client, bus)
    # 끊긴 사이의 행동 — 이 이벤트는 잃을 수 있다(at-most-once)
    target = state.get_valid_pawn_moves()[0]
    await games.move(state.game_id, 1, target.row, target.col)

    await eventually(lambda: bus.resubscribes == 1 and bus.subscribed)
    # 재동기화가 최신 상태를 보낸다 — 잃은 이벤트가 있어도 수렴한다
    for ws in (ws1, ws2):
        await eventually(lambda ws=ws: any(
            m["type"] == GAME_STATE and m["payload"]["turn_count"] == 1 for m in ws.sent_messages
        ))

    # 재구독 후에는 다시 정상 전달된다
    ws1.sent_messages.clear()
    target = (await games.load_game(state.game_id)).get_valid_pawn_moves()[0]
    await games.move(state.game_id, 2, target.row, target.col)
    await eventually(lambda: events.GAME_UPDATED in types(ws1))

    # 다른 워커는 영향을 받지 않았다
    assert workers[1][1].resubscribes == 0


async def test_resync_by_activity(redis_client, games, rooms, mm, delivery):
    state = await start_game(games, "duel", [1, 2])
    room = await rooms.create_room(GAME, "trio", 3, "host")
    await mm.join(GAME, "trio", 4, "q4", 1000)
    for uid in (5, 6):
        result = await mm.join(GAME, "duel", uid, f"n{uid}", 1000)

    [game_msg] = await delivery.resync(1)
    assert game_msg["type"] == GAME_STATE and game_msg["payload"]["game_id"] == state.game_id

    [room_msg] = await delivery.resync(3)
    assert room_msg["type"] == events.ROOM_UPDATED and room_msg["payload"]["code"] == room.code

    [queue_msg] = await delivery.resync(4)
    assert queue_msg["type"] == QUEUE_STATUS and queue_msg["payload"]["position"] == 1

    [match_msg] = await delivery.resync(5)
    assert match_msg["type"] == events.MATCHED
    assert match_msg["payload"]["match_id"] == result.match.match_id
    assert match_msg["payload"]["my_seat_no"] in (1, 2)

    assert await delivery.resync(77) == []


# ----- 정지 -----

async def test_stop_releases_connection(redis_client, delivery):
    manager = ConnectionManager()
    bus = EventBus(manager, delivery)
    await bus.start()
    ws = await connect(manager, 1)
    await bus.stop()
    assert not bus.subscribed

    e = Event(events.ROOM_DISSOLVED, "room", "STOPPD", (1,), {"code": "STOPPD"})
    await redis_client.publish(e.channel, e.to_json())
    await asyncio.sleep(0.1)
    assert ws.sent_messages == []

    names = [c.get("name", "") for c in await redis_client.client_list()]
    assert bus.name not in names
    assert not any(t.get_name() == bus.name for t in asyncio.all_tasks())


async def test_no_bus_connections_leak(redis_client):
    """다른 테스트가 끝난 뒤 버스 연결이 남지 않는다 (픽스처 정리 확인)"""
    names = [c.get("name", "") for c in await redis_client.client_list()]
    assert not [n for n in names if n.startswith(CLIENT_NAME_PREFIX)]


# ----- 시간 체계 (M3 6단계) -----

async def test_disconnect_event_reaches_other_worker(workers, games):
    sockets = {uid: await connect(workers[i][0], uid) for i, uid in enumerate((1, 2))}
    state = await start_game(games, "duel", [1, 2])
    await games.mark_disconnected(state.game_id, 2)
    await eventually(lambda: events.SEAT_DISCONNECTED in types(sockets[1]))
    msg = next(m for m in sockets[1].sent_messages if m["type"] == events.SEAT_DISCONNECTED)
    assert msg["payload"]["seat_no"] == 2 and positions_in(msg["payload"]) == []


async def test_resync_game_state_carries_clocks(redis_client, games, delivery):
    state = await start_game(games, "duel", [1, 2])
    [msg] = await delivery.resync(1)
    clocks = msg["payload"]["clocks"]
    assert [c["seat_no"] for c in clocks["seats"]] == [1, 2]
    assert clocks["current_expires_at_ms"] is not None
