"""
maze WS 핸들러 — 실제 uvicorn(스레드) + 실제 Redis(논리 DB 1) + 프로세스 내 버스 (M3 7단계 A3)

기준: A1(close code) · A2(페이로드 위조 무효) · A3(코드·고정 문구만) · A5(좌석별) · A6(끊김·재접속·4000) ·
A8(탈락자) · A9(관전 설정). DB 는 쓰지 않는다 — 신원은 가짜 디렉토리.
"""

import asyncio
import json
import re

import pytest
import pytest_asyncio

from app.core.worker import WORKER_ID
from app.db import redis_keys as keys
from app.services.identity import Identity, IdentityUnavailable
from app.ws.protocol import MESSAGES
from tests.conftest import mint_token
from tests.ws.live import Client, LiveServer, build_app, build_handler, purge, raw_redis

UNKNOWN_USER, BROKEN_STORE, NO_NICK = 9_000, 9_001, 9_002


class FakeIdentity:
    async def lookup(self, user_id: int):
        if user_id == UNKNOWN_USER:
            return None
        if user_id == BROKEN_STORE:
            raise IdentityUnavailable("down")
        return Identity(user_id, None if user_id == NO_NICK else f"u{user_id}", 1000)


@pytest.fixture(scope="module")
def server():
    from app.core.config import settings
    from tests.conftest import TEST_JWT_SECRET

    old = settings.jwt_secret_key
    settings.jwt_secret_key = TEST_JWT_SECRET
    handler = build_handler(FakeIdentity())
    live = LiveServer(build_app(handler)).start()
    live.handler = handler
    yield live
    live.stop()
    settings.jwt_secret_key = old


@pytest_asyncio.fixture
async def redis(server):
    client = raw_redis()
    await purge(client)
    yield client
    await purge(client)
    await client.aclose()


@pytest_asyncio.fixture
async def clients(server, redis):
    opened: list[Client] = []

    async def make(*user_ids: int) -> list[Client]:
        out = [await Client(server, uid).open() for uid in user_ids]
        opened.extend(out)
        return out

    yield make
    for c in opened:
        await c.close()


def all_text(clients) -> str:
    return json.dumps([m for c in clients for m in c.received], ensure_ascii=False)


async def start_ranked(clients, mode: str, seats: int, base: int = 100) -> tuple[list[Client], str]:
    """큐 → 매칭 → 전원 ready → game_start. 좌석 순서대로 정렬한 클라이언트와 game_id"""
    cs = await clients(*range(base, base + seats))
    for c in cs:
        seq = await c.send("join_queue", {"mode": mode})
        assert (await c.reply(seq))["type"] == "queue_joined"
    for c in cs:
        c.matched = await c.recv("matched")
    for c in cs:
        await c.send("ready")
    for c in cs:
        c.start = await c.recv("game_start")
        c.seat_no = c.start["payload"]["my_seat_no"]
        c.view = (await c.recv("game_state"))["payload"]
        await c.recv("turn_change")
    cs.sort(key=lambda c: c.seat_no)
    return cs, cs[0].start["payload"]["game_id"]


async def seat_owners(redis, game_id: str) -> dict[int, str]:
    """좌석 owner(연결 id) — 게임 시작 때의 기록은 버스 밖 태스크라(검토 R8) 잠깐 기다린다"""
    for _ in range(150):
        clocks = json.loads(await redis.get(keys.game_clocks(game_id)))
        owners = {s["seat_no"]: s["owner"] for s in clocks["seats"]}
        if all(owners.values()):
            return owners
        await asyncio.sleep(0.02)
    raise AssertionError(f"seat owners not recorded: {owners}")


def legal_move(view: dict) -> tuple[int, int]:
    """내 칸의 열린 변으로 한 칸 — 발견 맵(내 4면)만으로 정한다(§5 클라이언트 자족)"""
    r, c = view["me"]["position"]["row"], view["me"]["position"]["col"]
    edges = {(e["row"], e["col"], e["orientation"]): e["wall"] for e in view["visible_edges"]}
    for (dr, dc), edge in {(-1, 0): (r, c, "horizontal"), (1, 0): (r + 1, c, "horizontal"),
                           (0, -1): (r, c, "vertical"), (0, 1): (r, c + 1, "vertical")}.items():
        if 0 <= r + dr <= 8 and 0 <= c + dc <= 8 and edges.get(edge) is False:
            return r + dr, c + dc
    raise AssertionError("no open edge")


# ----- 인증 (A1) -----

@pytest.mark.parametrize("token, code", [
    ("", 4001), ("garbage", 4001),
    (mint_token(1, typ="refresh"), 4001), (mint_token(1, exp_offset_sec=-1), 4001),
    (mint_token(1, secret="x" * 40), 4001), (mint_token(UNKNOWN_USER), 4001),
    (mint_token(1, auth="anonymous"), 4002), (mint_token(NO_NICK), 4003),
    (mint_token(BROKEN_STORE), 1013),
])
async def test_handshake_close_codes(server, redis, token, code):
    c = await Client(server, 1).open(token, expect_connected=False)
    assert await c.closed_code() == code
    assert c.received == []          # 닫기 전 어떤 메시지도 없다


async def test_no_token_param(server, redis):
    from websockets.asyncio.client import connect

    c = Client(server, 1)
    c.ws = await connect(server.url(None))
    assert await c.closed_code() == 4001


async def test_connected_payload(clients):
    [c] = await clients(5)
    assert c.connected["payload"] == {"user_id": 5, "nickname": "u5", "mmr": 1000}


# ----- 흐름 (A5) -----

async def test_ranked_game_per_seat(clients, seat_mode):
    """quad 는 배치 테이블에 행만 넣은 모드 — 핸들러·매칭·전달이 인원 수를 모른다"""
    mode, seats = seat_mode
    cs, game_id = await start_ranked(clients, mode, seats)
    assert [c.seat_no for c in cs] == list(range(1, seats + 1))
    for c in cs:
        assert c.view["me"]["seat_no"] == c.seat_no and "spectator" not in c.view

    row, col = legal_move(cs[0].view)
    seq = await cs[0].send("move", {"row": row, "col": col})
    for c in cs:
        turn = await c.recv("turn_change", last_action={"seat_no": 1, "kind": "move"})
        assert turn["payload"]["current_seat_no"] == 2
    assert all(m.get("ack_seq") != seq for m in cs[0].received)   # 수락에는 직접 응답이 없다

    for c in cs[1:]:
        await c.send("surrender")
    for c in cs:
        end = await c.recv("game_end")
        assert end["payload"]["reason"] == "last_standing" and end["payload"]["full_board"]
    for c in cs:   # 종료 전 메시지에 전체 판이 없다
        before = c.received[:next(i for i, m in enumerate(c.received) if m["type"] == "game_end")]
        assert "full_board" not in json.dumps(before) and "wall_manager" not in json.dumps(c.received)


async def test_room_flow_and_spectate_setting(clients):
    host, g2, g3 = await clients(21, 22, 23)
    seq = await host.send("create_room", {"mode": "trio"})
    created = await host.reply(seq)
    assert created["type"] == "room_created" and created["payload"]["allow_spectate"] is False
    code = created["payload"]["room_code"]
    for g in (g2, g3):
        joined = await g.reply(await g.send("join_room", {"room_code": code}))
        assert joined["type"] == "room_joined" and "user_id" not in json.dumps(joined)
    await host.recv("player_joined", seat_no=3)

    changed = await host.reply(await host.send("create_room", {"mode": "trio", "allow_spectate": True}))
    assert changed["type"] == "room_joined" and changed["payload"]["allow_spectate"] is True
    assert (await g2.recv("room_joined"))["payload"]["allow_spectate"] is True
    refused = await g2.reply(await g2.send("create_room", {"mode": "trio", "allow_spectate": False}))
    assert refused["payload"]["error"] == "already_in_room"

    for c in (host, g2, g3):
        await c.send("ready")
    for c in (host, g2, g3):
        start = await c.recv("game_start")
    late = await host.reply(await host.send("create_room", {"mode": "trio", "allow_spectate": False}))
    assert late["payload"]["error"] == "already_in_game"
    assert start["payload"]["mode"] == "trio"


# ----- 위조·누설 (A2·A3) -----

async def test_payload_seat_and_clock_are_ignored(clients, redis):
    cs, game_id = await start_ranked(clients, "duel", 2, base=300)
    second = cs[1]
    row, col = legal_move(cs[0].view)
    forged = await second.send("move", {"row": row, "col": col, "seat_no": 1, "user_id": cs[0].user_id,
                                        "remaining_ms": 999_999})
    err = await second.reply(forged)
    assert err["payload"] == {"error": "not_your_turn", "message": MESSAGES["not_your_turn"]}
    state = json.loads(await redis.get(keys.game_state(game_id)))
    assert state["turn_count"] == 0                                  # 아무것도 바뀌지 않았다


async def test_rejections_are_codes_only(clients):
    cs, _ = await start_ranked(clients, "duel", 2, base=400)
    first = cs[0]
    bad = [
        ("move", {"row": 0, "col": 0}, "invalid_move"),
        ("move", {"row": 99, "col": -3}, "invalid_move"),
        ("wall", {"row": 42, "col": 1, "orientation": "horizontal"}, "invalid_wall_position"),
        ("wall", {"row": 1, "col": 1, "orientation": "diagonal"}, "invalid_wall_position"),
        ("move", {"row": "1", "col": 1}, "invalid_request"),
        ("join_queue", {"mode": "duel"}, "already_in_game"),
        ("join_queue", {"mode": "nope"}, "invalid_request"),
        ("leave_queue", None, "not_in_queue"),
    ]
    for type_, payload, code in bad:
        err = await first.reply(await first.send(type_, payload))
        assert err["type"] == "error" and err["payload"] == {"error": code, "message": MESSAGES[code]}, type_
    raw_bad = ["not json", '{"type": "game_state"}', '{"type": "move", "seq": "x"}']
    for raw in raw_bad:
        await first.send("", raw=raw)
        err = await first.recv("error")
        assert err["payload"]["error"] == "invalid_request"
    await first.ws.send(b"\x00\x01")
    assert (await first.recv("error"))["payload"]["error"] == "invalid_request"
    # 예외 문구·좌표 표기가 어디에도 없다
    text = all_text(cs)
    assert not re.search(r"Wall\(|Position\(|Traceback|ValueError|\(\d+, \d+\)", text)


async def test_unknown_mode_is_invalid_request(clients):
    [c] = await clients(450)
    err = await c.reply(await c.send("join_queue", {"mode": "octo"}))
    assert err["payload"]["error"] == "invalid_request"


# ----- 끊김·재접속·교체 (A6) -----

async def test_disconnect_then_reconnect(server, clients, redis):
    cs, game_id = await start_ranked(clients, "duel", 2, base=500)
    first, second = cs
    second_conn_id = (await seat_owners(redis, game_id))[2]
    await second.close()
    left = await first.recv("player_left", state="reconnecting")
    assert left["payload"]["seat_no"] == 2 and left["payload"]["grace_remaining_ms"] > 0

    again = await Client(server, second.user_id).open()
    assert again.connected["payload"]["reconnect"] == {"game_id": game_id, "seat_no": 2}
    view = (await again.recv("game_state"))["payload"]
    # mark_connected 가 재동기화보다 먼저 — 재동기화 화면에서 이미 연결 상태다
    assert next(c for c in view["clocks"] if c["seat_no"] == 2)["connected"] is True
    await again.recv("turn_change")
    back = await first.recv("player_joined")
    assert back["payload"] == {"seat_no": 2, "state": "reconnected"}
    clocks = json.loads(await redis.get(keys.game_clocks(game_id)))
    # owner 는 연결 id — 새 연결의 것이다(같은 워커의 옛 연결과 구분된다, 검토 R1)
    owner = {s["seat_no"]: s["owner"] for s in clocks["seats"]}[2]
    assert owner.startswith(server.handler.worker_id + ":") and owner != second_conn_id
    await again.close()


async def test_seat_owner_recorded_at_game_start(clients, redis):
    cs, game_id = await start_ranked(clients, "trio", 3, base=550)
    owners = await seat_owners(redis, game_id)
    assert {o.split(":")[0] for o in owners.values()} == {WORKER_ID}
    assert len(set(owners.values())) == 3                           # 좌석마다 자기 연결


async def test_same_worker_replacement_is_not_a_disconnect(server, clients):
    cs, _ = await start_ranked(clients, "duel", 2, base=600)
    first, second = cs
    newer = await Client(server, second.user_id).open()
    assert await second.closed_code() == 4000
    await newer.recv("game_state")
    noise = await first.quiet(0.5)
    assert not [m for m in noise if m["type"] == "player_left"]   # 교체는 끊김이 아니다
    await newer.close()


# ----- 탈락자 (A8) -----

async def test_eliminated_seat_can_only_watch_or_leave(clients, redis):
    cs, game_id = await start_ranked(clients, "trio", 3, base=700)
    third = cs[2]
    await third.send("surrender")
    await third.recv("player_left", state="eliminated")
    for type_, payload in (("move", {"row": 1, "col": 1}), ("surrender", None), ("chat", {"text": "hi"})):
        err = await third.reply(await third.send(type_, payload))
        assert err["payload"]["error"] == "not_in_game", type_
    alive_chat = await cs[0].reply(await cs[0].send("chat", {"text": "hi"}))
    assert alive_chat["payload"]["error"] == "feature_disabled"

    left = await third.reply(await third.send("leave_room"))
    assert left["type"] == "player_left" and left["payload"]["seat_no"] == 3
    assert await redis.get(keys.user_activity(third.user_id)) is None
    joined = await third.reply(await third.send("join_queue", {"mode": "duel"}))
    assert joined["type"] == "queue_joined"
    state = json.loads(await redis.get(keys.game_state(game_id)))
    assert next(p for p in state["seats"] if p["seat_no"] == 3)["elimination_reason"] == "surrender"


async def test_alive_leave_room_in_game_is_surrender(clients):
    cs, _ = await start_ranked(clients, "duel", 2, base=800)
    await cs[1].send("leave_room")
    end = await cs[0].recv("game_end")
    assert end["payload"]["reason"] == "last_standing"


# ----- 접속 처리 실패 (독립 검토 #1 R3·R7) -----

async def test_failed_reconnect_closes_1013_and_leaves_nothing(server, clients, monkeypatch):
    """재접속 때 좌석 소유를 못 가져가면 반쯤 열린 연결로 두지 않는다 — connected 없이 1013, 연결 맵에 없음"""
    from app.services.maze_game import GameBusy

    cs, _ = await start_ranked(clients, "duel", 2, base=1_000)
    second = cs[1]
    games = server.handler.games

    async def busy(*args, **kwargs):
        raise GameBusy("contended")

    monkeypatch.setattr(games, "mark_connected", busy)
    again = await Client(server, second.user_id).open(mint_token(second.user_id), expect_connected=False)
    assert await again.closed_code() == 1013
    assert again.received == []
    await asyncio.sleep(0.1)
    assert server.handler.manager.get_connection(second.user_id) is None
