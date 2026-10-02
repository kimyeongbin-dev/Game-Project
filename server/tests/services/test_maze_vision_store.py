"""
좌석별 누적 시야의 Redis 저장 — maze.md §6 (M3 5단계 계획서 판단 3·6)

`game:{id}:vision:{seat_no}` 가 state 와 같은 락·같은 펜싱 쓰기 한 번으로 기록되는지 본다.
DB 는 쓰지 않는다(`games_no_db`).
"""

import json

import pytest

from app.db import redis_keys as keys
from app.games.maze.core.board import Position
from app.games.maze.core.vision import SeatMemory, game_sight
from app.services.maze_game import GameBusy, MazeGameService, SeatPlayer


async def start(games, mode, seats, **kwargs):
    users = list(range(301, 301 + seats))
    state = await games.create_game(
        mode=mode, is_ranked=kwargs.pop("is_ranked", False),
        players=[SeatPlayer(i + 1, uid, f"p{uid}") for i, uid in enumerate(users)],
        **kwargs,
    )
    return state, users


def vision_keys(game_id, seats):
    return [keys.game_vision(game_id, s) for s in range(1, seats + 1)]


async def memories(redis, game_id, seats) -> dict[int, SeatMemory]:
    raws = await redis.mget(*vision_keys(game_id, seats))
    return {s: SeatMemory.from_dict(json.loads(raw)) for s, raw in enumerate(raws, start=1)}


async def place_seat(redis, game_id, seat_no, row, col):
    """테스트 배치 — 저장된 state 의 말 위치를 직접 바꾼다 (규칙 경로 밖)"""
    data = json.loads(await redis.get(keys.game_state(game_id)))
    for seat in data["seats"]:
        if seat["seat_no"] == seat_no:
            seat["position"] = {"row": row, "col": col}
    await redis.set(keys.game_state(game_id), json.dumps(data))


async def test_initial_vision_for_every_seat(games_no_db, redis_client, seat_mode):
    mode, seats = seat_mode
    state, _ = await start(games_no_db, mode, seats)

    stored = await memories(redis_client, state.game_id, seats)
    for seat_no in range(1, seats + 1):
        assert stored[seat_no] == SeatMemory().observe(game_sight(state, seat_no), 0)
        assert await redis_client.ttl(keys.game_vision(state.game_id, seat_no)) == -1


async def test_accepted_action_updates_every_seat(games_no_db, redis_client, seat_mode):
    mode, seats = seat_mode
    state, users = await start(games_no_db, mode, seats)
    before = await memories(redis_client, state.game_id, seats)

    target = state.get_valid_pawn_moves()[0]
    assert (await games_no_db.move(state.game_id, users[0], target.row, target.col)).rejection is None

    loaded = await games_no_db.load_game(state.game_id)
    after = await memories(redis_client, state.game_id, seats)
    for seat_no in range(1, seats + 1):
        assert after[seat_no] == before[seat_no].observe(game_sight(loaded, seat_no), 1)


async def test_others_moves_change_my_vision(games_no_db, redis_client):
    """남의 이동이 내 시야를 바꾸고, 시야 밖으로 나가면 마지막 목격이 그대로 남는다"""
    state, users = await start(games_no_db, "duel", 2)       # seat1 (8,4), seat2 (0,4)
    await place_seat(redis_client, state.game_id, 2, 6, 4)

    await games_no_db.move(state.game_id, users[0], 7, 4)     # turn 1: seat2 가 b 에 보인다
    assert (await memories(redis_client, state.game_id, 2))[1].last_seen == {2: (Position(6, 4), 1)}

    await games_no_db.move(state.game_id, users[1], 6, 3)     # turn 2: a 로 — 여전히 보인다
    assert (await memories(redis_client, state.game_id, 2))[1].last_seen == {2: (Position(6, 3), 2)}

    await games_no_db.place_wall(state.game_id, users[0], 0, 0, "horizontal")   # turn 3: 아직 보인다
    assert (await memories(redis_client, state.game_id, 2))[1].last_seen == {2: (Position(6, 3), 3)}

    await games_no_db.move(state.game_id, users[1], 5, 3)     # turn 4: 시야 밖
    mine = (await memories(redis_client, state.game_id, 2))[1]
    assert mine.last_seen == {2: (Position(6, 3), 3)}        # 채워 넣지 않는다


async def test_rejection_leaves_vision_untouched(games_no_db, redis_client, seat_mode):
    mode, seats = seat_mode
    state, users = await start(games_no_db, mode, seats)
    await games_no_db.place_wall(state.game_id, users[0], 3, 3, "horizontal")
    before = await redis_client.mget(*vision_keys(state.game_id, seats))

    rejected = await games_no_db.place_wall(state.game_id, users[1], 3, 3, "horizontal")
    assert rejected.rejection == "invalid_wall_position"
    assert await redis_client.mget(*vision_keys(state.game_id, seats)) == before


async def test_eliminated_seat_is_frozen(games_no_db, redis_client, seat_mode):
    """탈락 좌석은 눈을 감는다 — 탈락 직전 관측 그대로 (계획서 판단 3)"""
    mode, seats = seat_mode
    state, users = await start(games_no_db, mode, seats)
    frozen_key = keys.game_vision(state.game_id, seats)
    frozen = await redis_client.get(frozen_key)

    await games_no_db.surrender(state.game_id, users[-1])
    assert await redis_client.get(frozen_key) == frozen

    loaded = await games_no_db.load_game(state.game_id)
    while not loaded.is_finished and loaded.turn_count < 6:
        seat = loaded.current_seat_no
        target = loaded.get_valid_pawn_moves()[0]
        await games_no_db.move(state.game_id, users[seat - 1], target.row, target.col)
        loaded = await games_no_db.load_game(state.game_id)
        assert await redis_client.get(frozen_key) == frozen


async def test_finished_game_vision_expires_with_state(games_no_db, redis_client, seat_mode):
    mode, seats = seat_mode
    state, users = await start(games_no_db, mode, seats)
    for uid in users[1:]:
        await games_no_db.surrender(state.game_id, uid)        # 마지막 생존자만 남는다

    assert (await games_no_db.load_game(state.game_id)).is_finished
    state_ttl = await redis_client.ttl(keys.game_state(state.game_id))
    assert state_ttl > 0
    for key in vision_keys(state.game_id, seats):
        assert abs(await redis_client.ttl(key) - state_ttl) <= 1


async def test_lost_lock_writes_neither_state_nor_vision(games_no_db, redis_client, monkeypatch):
    """state 와 시야는 전부 또는 전무 — 관측 계산 중 락을 잃으면 아무것도 쓰지 않는다"""
    state, users = await start(games_no_db, "trio", 3)
    before = await redis_client.mget(
        keys.game_state(state.game_id), *vision_keys(state.game_id, 3)
    )
    observe_all = MazeGameService._observe_all

    async def steal_lock(self, redis, s):
        out = await observe_all(self, redis, s)
        await redis.set(keys.game_lock(state.game_id), "someone-else")   # 만료 후 남이 잡았다
        return out

    monkeypatch.setattr(MazeGameService, "_observe_all", steal_lock)
    target = state.get_valid_pawn_moves()[0]
    with pytest.raises(GameBusy):
        await games_no_db.move(state.game_id, users[0], target.row, target.col)

    after = await redis_client.mget(keys.game_state(state.game_id), *vision_keys(state.game_id, 3))
    assert after == before
    await redis_client.delete(keys.game_lock(state.game_id))


async def test_void_lost_game_removes_vision(games_no_db, redis_client, seat_mode):
    mode, seats = seat_mode
    state, _ = await start(games_no_db, mode, seats)
    await redis_client.delete(keys.game_state(state.game_id))      # 유실

    await games_no_db.void_lost_game(state.game_id)
    assert await redis_client.exists(*vision_keys(state.game_id, seats)) == 0


async def test_ranked_game_cannot_allow_spectating(games_no_db):
    with pytest.raises(ValueError):
        await start(games_no_db, "duel", 2, is_ranked=True, spectate_on_elimination=True)
