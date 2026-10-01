"""
좌석별 화면 — §6 필터 자리 (M3 4단계 판단 4)

시야 계산(5단계) 전의 기본값은 "아무것도 보여 주지 않는다"이다. 남의 좌표·벽이 패킷
어디에도 없다는 것을 고정한다. DB 는 쓰지 않는다.
"""

import json

import pytest

from app.services.maze_game import MazeGameService, SeatPlayer
from app.services.maze_view import game_view


@pytest.fixture
def games(redis_client) -> MazeGameService:
    return MazeGameService(lambda: None)


async def start(games, mode, seats):
    users = list(range(201, 201 + seats))
    state = await games.create_game(
        mode=mode, is_ranked=False,
        players=[SeatPlayer(i + 1, uid, f"p{uid}") for i, uid in enumerate(users)],
    )
    return state, users


def positions_in(obj) -> list[dict]:
    """패킷 안의 모든 {row, col} 쌍"""
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


async def test_no_other_coordinates_anywhere(games, seat_mode):
    """§6 MUST NOT — 시야 밖 좌표를 어떤 필드로든 싣지 않는다"""
    mode, seats = seat_mode
    state, users = await start(games, mode, seats)
    # 벽을 하나 세워 둔다 — 벽 목록도 새면 안 된다
    await games.place_wall(state.game_id, users[0], 3, 3, "horizontal")

    for seat_no, uid in enumerate(users, start=1):
        view = await game_view(state.game_id, uid, games=games)
        assert positions_in(view) == [view["me"]["position"]]
        raw = json.dumps(view)
        assert "walls\"" not in raw and "wall_manager" not in raw
        assert view["visible_edges"] == view["discovered_edges"] == []
        assert view["visible_players"] == view["last_seen_players"] == []
        assert all(o["visible"] is False for o in view["others"])


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


async def test_non_participant_and_missing_game(games):
    state, users = await start(games, "duel", 2)
    assert await game_view(state.game_id, 999, games=games) is None
    assert await game_view("no-such-game", users[0], games=games) is None
