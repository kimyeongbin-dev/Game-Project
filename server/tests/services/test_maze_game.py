"""
게임 서비스 — Redis 권위 상태 + 게임별 락 + 종료 기록

모든 좌석 관련 테스트가 duel·trio·quad 에서 돈다. quad 는 배치 테이블 행 추가뿐이다.
"""

import asyncio
import json
import random

import pytest

from app.db import redis_keys as keys
from app.db.redis_lock import StoreUnavailable
from app.db.repository import GameSessionRepository
from app.services.maze_game import GameNotFound, SeatPlayer, StateVersionMismatch


async def start(games, make_users, mode: str, seats: int, **kwargs):
    user_ids = await make_users(seats)
    players = [SeatPlayer(seat_no=i + 1, user_id=uid, nickname=f"p{i + 1}") for i, uid in enumerate(user_ids)]
    state = await games.create_game(
        mode=mode, is_ranked=kwargs.pop("is_ranked", True), players=players,
        rng=random.Random(0), **kwargs,
    )
    return state, user_ids


async def db_record(session_factory, game_id):
    async with session_factory() as session:
        return await GameSessionRepository(session).get_by_id(game_id)


# ----- 생성·조회 -----

async def test_create_then_load_round_trip(games, make_users, session_factory, redis_client, seat_mode):
    mode, seats = seat_mode
    state, user_ids = await start(games, make_users, mode, seats)

    loaded = await games.load_game(state.game_id)
    assert loaded.to_dict() == state.to_dict()

    meta = await games.get_meta(state.game_id)
    assert [p.seat_no for p in meta.players] == list(range(1, seats + 1))
    assert meta.human_user_ids == user_ids
    for uid in user_ids:
        assert await redis_client.get(keys.user_activity(uid)) == keys.activity_game(state.game_id)
    # 진행 중 상태에는 TTL 이 없다
    assert await redis_client.ttl(keys.game_state(state.game_id)) == -1

    record = await db_record(session_factory, state.game_id)
    assert record.status == "in_progress"
    assert record.mode == mode
    assert [p.seat_no for p in record.participants] == list(range(1, seats + 1))


async def test_create_rejects_seats_not_matching_layout(games, make_users):
    user_ids = await make_users(3)
    players = [SeatPlayer(i + 1, uid, f"p{i}") for i, uid in enumerate(user_ids)]
    with pytest.raises(ValueError):
        await games.create_game(mode="duel", is_ranked=False, players=players)


async def test_load_missing_game_returns_none(games):
    assert await games.load_game("no-such-game") is None
    with pytest.raises(GameNotFound):
        await games.move("no-such-game", 1, 0, 0)


async def test_schema_version_mismatch_is_refused(games, make_users, redis_client):
    state, user_ids = await start(games, make_users, "duel", 2)
    data = state.to_dict()
    data["schema_version"] = 0
    await redis_client.set(keys.game_state(state.game_id), json.dumps(data))

    with pytest.raises(StateVersionMismatch):
        await games.load_game(state.game_id)
    with pytest.raises(StateVersionMismatch):
        await games.move(state.game_id, user_ids[0], 7, 4)


# ----- 행동 -----

async def test_not_your_turn_and_not_in_game(games, make_users, seat_mode):
    mode, seats = seat_mode
    state, user_ids = await start(games, make_users, mode, seats)
    target = state.get_valid_pawn_moves()[0]

    outcome = await games.move(state.game_id, user_ids[1], target.row, target.col)
    assert outcome.rejection == "not_your_turn"

    outcome = await games.move(state.game_id, 999_999, target.row, target.col)
    assert outcome.rejection == "not_in_game"

    assert (await games.load_game(state.game_id)).turn_count == 0


async def test_concurrent_actions_are_serialized(games, make_users, seat_mode):
    """같은 수를 동시에 5번 보내도 정확히 1건만 수락된다 — 게임별 락"""
    mode, seats = seat_mode
    state, user_ids = await start(games, make_users, mode, seats)
    target = state.get_valid_pawn_moves()[0]

    outcomes = await asyncio.gather(*(
        games.move(state.game_id, user_ids[0], target.row, target.col) for _ in range(5)
    ))
    assert [o.rejection for o in outcomes].count(None) == 1
    assert {o.rejection for o in outcomes} == {None, "not_your_turn"}

    loaded = await games.load_game(state.game_id)
    assert loaded.turn_count == 1
    assert loaded.current_seat_no == 2


async def test_rejected_wall_attempts_are_persisted(games, make_users, seat_mode):
    """거절도 저장한다 — 벽 거절은 wall_rejections 를 바꾼다 (§7)"""
    mode, seats = seat_mode
    state, user_ids = await start(games, make_users, mode, seats)

    first = await games.place_wall(state.game_id, user_ids[0], 3, 3, "horizontal")
    assert first.rejection is None
    for _ in range(2):
        overlap = await games.place_wall(state.game_id, user_ids[1], 3, 3, "horizontal")
        assert overlap.rejection == "invalid_wall_position"

    assert (await games.load_game(state.game_id)).wall_rejections == 2


async def test_surrender_eliminates_seat(games, make_users, seat_mode):
    mode, seats = seat_mode
    state, user_ids = await start(games, make_users, mode, seats)

    outcome = await games.surrender(state.game_id, user_ids[0])
    assert outcome.rejection is None
    assert outcome.state.seat(1).elimination_reason == "surrender"

    if seats == 2:
        assert outcome.ended
        assert outcome.state.end_reason.value == "last_standing"
        assert outcome.state.winner_seat_no == 2
    else:
        assert not outcome.ended
        assert outcome.state.current_seat_no == 2
        # 탈락한 좌석은 더 이상 행동할 수 없다
        again = await games.surrender(state.game_id, user_ids[0])
        assert again.rejection == "not_in_game"


async def test_server_elimination(games, make_users, seat_mode):
    """6단계 스위퍼가 쓰는 진입점 — 유저가 아니라 좌석으로 탈락시킨다"""
    mode, seats = seat_mode
    state, _ = await start(games, make_users, mode, seats)

    outcome = await games.eliminate(state.game_id, 1, "time_forfeit")
    assert outcome.state.seat(1).elimination_reason == "time_forfeit"
    assert outcome.ended == (seats == 2)


# ----- 종료 -----

async def test_game_end_is_recorded(games, make_users, session_factory, redis_client, seat_mode):
    """seat 1..N-1 이 차례로 항복 → seat N 이 last_standing 승리"""
    mode, seats = seat_mode
    state, user_ids = await start(games, make_users, mode, seats)

    for uid in user_ids[:-1]:
        outcome = await games.surrender(state.game_id, uid)
    assert outcome.ended

    final = outcome.state
    record = await db_record(session_factory, state.game_id)
    assert record.status == "finished"
    assert record.end_reason == "last_standing"
    assert record.winner_seat_no == seats
    assert record.turn_count == final.turn_count

    expected_rank = {s["seat_no"]: s["rank"] for s in final.standings()}
    for p in record.participants:
        assert p.rank == expected_rank[p.seat_no]
        assert p.result == ("win" if p.seat_no == seats else "lose")
        assert p.elimination_reason == (None if p.seat_no == seats else "surrender")
        assert p.mmr_before is None and p.mmr_after is None

    # 종료 후: 재접속자가 game_end 를 받을 수 있게 보존 기한만 걸고, 활동은 푼다
    assert await redis_client.ttl(keys.game_state(state.game_id)) > 0
    assert await redis_client.ttl(keys.game_meta(state.game_id)) > 0
    for uid in user_ids:
        assert await redis_client.get(keys.user_activity(uid)) is None

    after = await games.move(state.game_id, user_ids[-1], 0, 0)
    assert after.rejection == "game_already_ended"


async def test_runs_without_db(games_no_db, make_users):
    """DB 가 없어도 게임은 진행·종료된다 (기록만 없다)"""
    state, user_ids = await start(games_no_db, make_users, "duel", 2)
    outcome = await games_no_db.surrender(state.game_id, user_ids[0])
    assert outcome.ended


async def test_redis_unavailable_raises(games, make_users, monkeypatch):
    import app.db.redis as redis_module

    user_ids = await make_users(2)
    monkeypatch.setattr(redis_module, "_available", False)
    with pytest.raises(StoreUnavailable):
        await games.create_game(
            mode="duel", is_ranked=False,
            players=[SeatPlayer(i + 1, uid, f"p{i}") for i, uid in enumerate(user_ids)],
        )


async def test_void_lost_game(games, make_users, session_factory, redis_client, seat_mode):
    """Redis 상태 유실 → 무효 (§8 fail-safe). 감지는 6단계, 처리는 여기"""
    mode, seats = seat_mode
    state, user_ids = await start(games, make_users, mode, seats)
    await redis_client.delete(keys.game_state(state.game_id))

    await games.void_lost_game(state.game_id)

    record = await db_record(session_factory, state.game_id)
    assert record.status == "void"
    assert record.end_reason == "server_fault"
    assert {p.result for p in record.participants} == {"void"}
    assert await redis_client.get(keys.game_meta(state.game_id)) is None
    for uid in user_ids:
        assert await redis_client.get(keys.user_activity(uid)) is None
