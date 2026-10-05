"""
좌석별 화면 — §6 시야 필터 (M3 4단계 자리 → 5단계 실제 시야)

패킷의 모든 좌표가 "내 것 / 지금 보이는 말 / 내가 목격한 말 / 내가 본 변" 중 하나라는 것과
MUST NOT 표 4행, 탈락·관전, 좌석 위조를 고정한다. DB 는 쓰지 않는다.
"""

import inspect
import json
import random

import pytest

from app.db import redis_keys as keys
from app.games.maze import GameState
from app.games.maze.core.board import Position
from app.games.maze.core.vision import SeatMemory, game_sight
from app.games.maze.core.wall import Orientation, Wall
from app.services.maze_game import GameMeta, MazeGameService, SeatPlayer
from app.services.maze_view import build_view, game_view
from app.ws.delivery import Delivery

TOP_KEYS = {
    "game_id", "turn_count", "current_seat_no", "finished", "me", "others",
    "discovered_edges", "visible_edges", "visible_players", "last_seen_players",
    "clocks",
}
CLOCK_SEAT_KEYS = {"seat_no", "remaining_ms", "connection_remaining_ms", "connected"}
ME_KEYS = {"seat_no", "position", "walls_remaining", "goals", "eliminated"}
OTHER_KEYS = {"seat_no", "nickname", "walls_remaining", "visible", "eliminated"}
EDGE_KEYS = {"row", "col", "orientation", "wall"}
SPECTATOR_KEYS = {"walls", "positions", "views"}


@pytest.fixture
def games(redis_client, fake_clock) -> MazeGameService:
    # 시계 값이 화면에 들어간다 — 같은 시각에 두 번 본 화면이 같도록 가짜 시계
    return MazeGameService(lambda: None, clock=fake_clock)


async def start(games, mode, seats, *, first_user=201, **kwargs):
    users = list(range(first_user, first_user + seats))
    state = await games.create_game(
        mode=mode, is_ranked=False,
        players=[SeatPlayer(i + 1, uid, f"p{uid}") for i, uid in enumerate(users)],
        **kwargs,
    )
    return state, users


async def play(games, game_id, users, actions: int, seed: int = 0) -> GameState:
    """무작위 수를 둔다 (벽 30%). 끝나면 멈춘다"""
    rng = random.Random(seed)
    state = await games.load_game(game_id)
    for _ in range(actions):
        if state.is_finished:
            break
        uid = users[state.current_seat_no - 1]
        placed = rng.random() < 0.3 and (await games.place_wall(
            game_id, uid, rng.randrange(8), rng.randrange(8), rng.choice(("horizontal", "vertical"))
        )).rejection is None
        if not placed:
            target = rng.choice(state.get_valid_pawn_moves())
            await games.move(game_id, uid, target.row, target.col)
        state = await games.load_game(game_id)
    return state


def assert_whitelisted(view: dict, *, spectator: bool = False) -> None:
    """MUST NOT 1·4 — 정의된 필드 말고는 아무것도 없다 (전체 벽 목록·전체 상태 필드가 없다)"""
    assert set(view) == TOP_KEYS | ({"spectator"} if spectator else set())
    assert set(view["me"]) == ME_KEYS
    assert all(set(o) == OTHER_KEYS for o in view["others"])
    for name in ("discovered_edges", "visible_edges"):
        assert all(set(e) == EDGE_KEYS for e in view[name])
    assert all(set(p) == {"seat_no", "position"} for p in view["visible_players"])
    assert all(set(p) == {"seat_no", "position", "seen_at_turn"} for p in view["last_seen_players"])
    if view["clocks"] is not None:
        assert set(view["clocks"]) == {"seats", "current_expires_at_ms", "voided"}
        assert all(set(c) == CLOCK_SEAT_KEYS for c in view["clocks"]["seats"])


def as_set(edges: list[dict]) -> set[tuple]:
    return {(e["row"], e["col"], e["orientation"], e["wall"]) for e in edges}


# ----- 기본 -----

async def test_each_seat_sees_itself(games, seat_mode):
    mode, seats = seat_mode
    state, users = await start(games, mode, seats)

    for seat_no, uid in enumerate(users, start=1):
        view = await game_view(state.game_id, uid, games=games)
        assert view["me"]["seat_no"] == seat_no
        assert view["me"]["position"] == state.seat(seat_no).position.to_dict()
        assert view["me"]["goals"] == [g.to_dict() for g in state.seat(seat_no).goals]
        assert sorted(o["seat_no"] for o in view["others"]) == [
            s for s in range(1, seats + 1) if s != seat_no
        ]
        # 시작부터 내 칸의 보드 안 면은 보인다
        assert view["visible_edges"] and as_set(view["visible_edges"]) <= as_set(view["discovered_edges"])


async def test_only_seen_coordinates_after_play(games, redis_client, seat_mode):
    """MUST NOT 2 — 남의 좌표는 지금 보이거나 내가 목격한 것만. 보이는 말·변은 서버 계산과 같다"""
    mode, seats = seat_mode
    state, users = await start(games, mode, seats)
    state = await play(games, state.game_id, users, actions=12)

    for seat_no, uid in enumerate(users, start=1):
        view = await game_view(state.game_id, uid, games=games)
        assert_whitelisted(view)
        raw = json.dumps(view)
        assert '"walls"' not in raw and '"full_board"' not in raw

        now = game_sight(state, seat_no)
        assert view["visible_players"] == [
            {"seat_no": s, "position": p.to_dict()} for s, p in now.players
        ]
        assert as_set(view["visible_edges"]) == {
            (e.row, e.col, e.orientation.value, w) for e, w in now.edges.items()
        }
        assert {o["seat_no"] for o in view["others"] if o["visible"]} == {s for s, _ in now.players}
        # 보이지 않는 좌석은 마지막 목격 위치만 — 현재 위치가 아니어도 된다(낡은 정보)
        stored = SeatMemory.from_dict(json.loads(
            await redis_client.get(keys.game_vision(state.game_id, seat_no))
        ))
        assert {p["seat_no"]: (p["position"], p["seen_at_turn"]) for p in view["last_seen_players"]} == {
            s: (pos.to_dict(), turn) for s, (pos, turn) in stored.last_seen.items()
        }


def test_example_packet_shape():
    """§6 예시 모양 — P(4,4) 북쪽 + e 북쪽을 막는 벽 하나, 상대가 d 에 있다"""
    state = GameState("duel")
    state.seat(1).move_to(Position(4, 4))
    state.seat(2).move_to(Position(4, 3))
    state.wall_manager.add_wall(Wall(3, 4, Orientation.HORIZONTAL))   # P｜b, e｜c
    meta = GameMeta(state.game_id, "maze_1p", "duel", False, None, "t",
                    (SeatPlayer(1, 1, "a"), SeatPlayer(2, 2, "b")))

    view = build_view(state, meta, 1, SeatMemory())
    assert_whitelisted(view)

    def edge(r, c, o, w):
        return {"row": r, "col": c, "orientation": o, "wall": w}
    hz, vt = "horizontal", "vertical"
    assert view["visible_edges"] == [
        edge(4, 3, hz, False),   # d｜a
        edge(4, 4, hz, True),    # P｜b
        edge(4, 4, vt, False),   # d｜P
        edge(4, 5, hz, True),    # e｜c
        edge(4, 5, vt, False),   # P｜e
        edge(5, 3, hz, False),   # d｜f
        edge(5, 4, hz, False),   # P｜g
        edge(5, 4, vt, False),   # f｜g
        edge(5, 5, hz, False),   # e｜h
        edge(5, 5, vt, False),   # g｜h
    ]
    assert view["discovered_edges"] == view["visible_edges"]
    assert view["visible_players"] == [{"seat_no": 2, "position": {"row": 4, "col": 3}}]
    assert view["last_seen_players"] == [
        {"seat_no": 2, "position": {"row": 4, "col": 3}, "seen_at_turn": 0}
    ]
    assert view["others"][0]["visible"] is True


async def test_public_fields_are_shown(games):
    state, users = await start(games, "trio", 3)
    await games.place_wall(state.game_id, users[0], 3, 3, "horizontal")
    await games.surrender(state.game_id, users[2])

    view = await game_view(state.game_id, users[1], games=games)
    others = {o["seat_no"]: o for o in view["others"]}
    assert others[1]["walls_remaining"] == state.seat(1).walls_remaining - 1
    assert others[1]["nickname"] == f"p{users[0]}"
    assert others[3]["eliminated"] is True
    assert view["turn_count"] == 1


async def test_reads_only_my_vision_key(games, redis_client, seat_mode):
    """플레이어 화면은 다른 좌석의 관측을 읽지 않는다 — 지워도 내 화면이 같다"""
    mode, seats = seat_mode
    state, users = await start(games, mode, seats)
    await play(games, state.game_id, users, actions=4)
    before = await game_view(state.game_id, users[0], games=games)

    await redis_client.delete(*(keys.game_vision(state.game_id, s) for s in range(2, seats + 1)))
    assert await game_view(state.game_id, users[0], games=games) == before


# ----- 탈락·관전 -----

async def test_eliminated_seat_closes_eyes(games):
    """랭크·관전 끔 — 지금 보이는 것은 비고, 발견 맵은 탈락 직전 그대로, spectator 없음"""
    state, users = await start(games, "trio", 3)
    before = await game_view(state.game_id, users[2], games=games)
    await games.surrender(state.game_id, users[2])
    await play(games, state.game_id, users[:2] + [None], actions=4)

    view = await game_view(state.game_id, users[2], games=games)
    assert_whitelisted(view)
    assert view["me"]["eliminated"] is True
    assert view["visible_edges"] == [] and view["visible_players"] == []
    assert view["discovered_edges"] == before["discovered_edges"]
    assert view["last_seen_players"] == before["last_seen_players"]


async def test_spectator_packet_when_room_allows(games):
    """친구 방 관전 켬 — 탈락자에게만 전체 판 + 생존자별 시야"""
    state, users = await start(games, "trio", 3, spectate_on_elimination=True)
    await games.surrender(state.game_id, users[2])
    state = await play(games, state.game_id, users[:2] + [None], actions=6, seed=3)

    view = await game_view(state.game_id, users[2], games=games)
    assert_whitelisted(view, spectator=True)
    spec = view["spectator"]
    assert set(spec) == SPECTATOR_KEYS
    assert spec["walls"] == [w.to_dict() for w in state.wall_manager.walls]
    assert spec["positions"] == [
        {"seat_no": p.seat_no, "position": p.position.to_dict()} for p in state.seats
    ]
    survivors = [p.seat_no for p in state.survivors]
    assert [v["seat_no"] for v in spec["views"]] == survivors
    for v in spec["views"]:
        own = await game_view(state.game_id, users[v["seat_no"] - 1], games=games)
        assert "spectator" not in own                       # 생존자에게는 없다
        for field in ("discovered_edges", "visible_edges", "visible_players", "last_seen_players"):
            assert v[field] == own[field]


async def test_no_spectator_without_room_setting(games, seat_mode):
    mode, seats = seat_mode
    state, users = await start(games, mode, seats)
    await games.surrender(state.game_id, users[-1])
    for uid in users:
        assert "spectator" not in await game_view(state.game_id, uid, games=games)


async def test_finished_game_stays_fogged(games):
    """종료 후에도 전체 판은 화면에 없다 — full_board 는 game_end(7단계)에서만"""
    state, users = await start(games, "duel", 2)
    await games.surrender(state.game_id, users[1])
    for uid in users:
        view = await game_view(state.game_id, uid, games=games)
        assert view["finished"] is True
        assert_whitelisted(view)


# ----- 좌석 위조 (계획서 판단 9) -----

def test_no_seat_or_vision_input_in_service_api():
    """MUST NOT 3 — 클라이언트가 좌석·시야를 넘길 인자가 없다"""
    expected = {
        MazeGameService.move: ["self", "game_id", "user_id", "row", "col"],
        MazeGameService.place_wall: ["self", "game_id", "user_id", "row", "col", "orientation"],
        MazeGameService.surrender: ["self", "game_id", "user_id"],
        game_view: ["game_id", "user_id", "games"],
    }
    for fn, params in expected.items():
        assert list(inspect.signature(fn).parameters) == params


async def test_cannot_view_another_seat_or_game(games):
    state, users = await start(games, "trio", 3)
    other, outsiders = await start(games, "duel", 2, first_user=901)

    for seat_no, uid in enumerate(users, start=1):
        assert (await game_view(state.game_id, uid, games=games))["me"]["seat_no"] == seat_no
    assert await game_view(state.game_id, outsiders[0], games=games) is None   # 남의 게임 id
    assert await game_view(state.game_id, 999, games=games) is None
    assert await game_view("no-such-game", users[0], games=games) is None


# ----- 재접속 (§9) -----

async def test_resync_restores_discovered_map(games, redis_client):
    """재동기화는 저장된 발견 맵을 그대로 복원한다 — 지금 시야 밖의 변도 남아 있다"""
    state, users = await start(games, "duel", 2)               # seat1 (8,4)
    await games.move(state.game_id, users[0], 7, 4)
    await games.move(state.game_id, users[1], 1, 4)
    await games.move(state.game_id, users[0], 6, 4)            # (8,4) 북쪽 변은 이제 3×3 밖

    messages = await Delivery(games=games).resync(users[0])
    assert [m["type"] for m in messages] == ["game_state", "turn_change"]
    view = messages[0]["payload"]
    old = (8, 4, "horizontal", False)
    assert old in as_set(view["discovered_edges"])
    assert old not in as_set(view["visible_edges"])


# ----- 시계 (M3 6단계) -----

async def test_view_clocks_are_settled_public_values(games, fake_clock, seat_mode):
    """좌석 전원이 같은 시계를 본다 — 조회 시각 기준 정산 값, 좌표 없음"""
    from app.core.config import settings
    mode, seats = seat_mode
    t0 = fake_clock.ms
    state, users = await start(games, mode, seats)
    fake_clock.advance(10_000)
    await games.mark_disconnected(state.game_id, users[-1])
    fake_clock.advance(5_000)

    views = [await game_view(state.game_id, uid, games=games) for uid in users]
    expected = {
        "seats": [
            {"seat_no": s, "remaining_ms": settings.clock_initial_ms - (15_000 if s == 1 else 0),
             "connection_remaining_ms": settings.connection_budget_ms - (5_000 if s == seats else 0),
             "connected": s != seats}
            for s in range(1, seats + 1)
        ],
        "current_expires_at_ms": t0 + settings.clock_initial_ms,
        "voided": False,
    }
    for view in views:
        assert_whitelisted(view)
        assert view["clocks"] == expected
        assert not {"position", "row", "col"} & set(json.dumps(view["clocks"]).replace('"', " ").split())


async def test_eliminated_seat_sees_same_clocks(games, fake_clock):
    state, users = await start(games, "trio", 3)
    await games.surrender(state.game_id, users[2])
    fake_clock.advance(3_000)
    out = await game_view(state.game_id, users[2], games=games)
    alive = await game_view(state.game_id, users[0], games=games)
    assert out["clocks"] == alive["clocks"]
    assert out["visible_edges"] == [] and out["visible_players"] == []   # 5단계 동결은 그대로
