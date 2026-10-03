"""
매치메이킹 — Redis 큐, Lua 원자 매칭, ready → 게임 생성, 기한 만료 복귀 (maze.md §3)

정원은 배치 테이블에서만 온다. duel·trio·quad 파라미터화로 확인한다.
"""

import random

import pytest

from app.core.config import settings
from app.db import redis_keys as keys
from app.games.maze import GameState
from app.services.activity import MultiplayerError
from app.services.matchmaking import (
    READY_DEADLINE_SEC,
    MMR_WINDOW_CAP,
    Matchmaking,
    PendingMatch,
    mmr_window,
)
from app.services.maze_game import GAME

SEED = 7


@pytest.fixture
def mm(games_no_db, fake_clock) -> Matchmaking:
    return Matchmaking(games={GAME: games_no_db}, rng_factory=lambda: random.Random(SEED), clock=fake_clock)


async def fill(mm, mode, user_ids):
    """차례로 입장시키고 마지막 결과를 돌려준다"""
    result = None
    for uid in user_ids:
        result = await mm.join(GAME, mode, uid, f"n{uid}", 1000 + uid)
    return result


# ----- 큐 -----

async def test_match_forms_only_at_capacity(mm, redis_client, seat_mode):
    mode, seats = seat_mode
    users = list(range(1, seats + 1))

    for i, uid in enumerate(users[:-1]):
        result = await mm.join(GAME, mode, uid, f"n{uid}", 1000)
        assert result.match is None
        assert result.status.position == i + 1
        assert result.status.waiting_count == i + 1

    result = await mm.join(GAME, mode, users[-1], "last", 1000)
    match = result.match
    assert match is not None
    assert sorted(p.user_id for p in match.players) == users
    assert [p.seat_no for p in match.players] == list(range(1, seats + 1))
    assert result.status.waiting_count == 0
    for uid in users:
        assert await redis_client.get(keys.user_activity(uid)) == keys.activity_match(match.match_id)
        assert await redis_client.ttl(keys.user_activity(uid)) > 0


async def test_join_twice_is_idempotent(mm):
    await mm.join(GAME, "trio", 1, "a", 1000)
    result = await mm.join(GAME, "trio", 1, "a", 1000)
    assert result.status.waiting_count == 1


async def test_one_activity_per_user(mm, redis_client):
    await mm.join(GAME, "trio", 1, "a", 1000)
    with pytest.raises(MultiplayerError) as exc:
        await mm.join(GAME, "duel", 1, "a", 1000)
    assert exc.value.code == "already_in_queue"

    await redis_client.set(keys.user_activity(2), keys.activity_room("ABCDEF"))
    with pytest.raises(MultiplayerError) as exc:
        await mm.join(GAME, "duel", 2, "b", 1000)
    assert exc.value.code == "already_in_room"

    await redis_client.set(keys.user_activity(3), keys.activity_game("g"))
    with pytest.raises(MultiplayerError) as exc:
        await mm.join(GAME, "duel", 3, "c", 1000)
    assert exc.value.code == "already_in_game"


async def test_unknown_mode_is_rejected(mm):
    with pytest.raises(ValueError):
        await mm.join(GAME, "no-such-mode", 1, "a", 1000)


async def test_leave(mm, redis_client):
    await mm.join(GAME, "trio", 1, "a", 1000)
    await mm.leave(GAME, "trio", 1)

    status = await mm.status(GAME, "trio", 1)
    assert (status.position, status.waiting_count) == (0, 0)
    assert await redis_client.get(keys.user_activity(1)) is None
    with pytest.raises(MultiplayerError) as exc:
        await mm.leave(GAME, "trio", 1)
    assert exc.value.code == "not_in_queue"


async def test_fifo_and_overflow_stays_queued(mm, seat_mode):
    mode, seats = seat_mode
    users = list(range(1, seats + 2))  # 정원 + 1명
    first = None
    for uid in users:
        result = await mm.join(GAME, mode, uid, f"n{uid}", 1000)
        first = first or result.match
    assert sorted(p.user_id for p in first.players) == users[:-1]
    assert (await mm.status(GAME, mode, users[-1])).position == 1


async def test_seats_are_shuffled_deterministically(mm, seat_mode):
    """입장 순서가 아니라 rng 가 좌석을 정한다 — 먼저 왔다고 선수가 아니다"""
    mode, seats = seat_mode
    users = list(range(1, seats + 1))
    match = (await fill(mm, mode, users)).match

    expected = list(users)
    random.Random(SEED).shuffle(expected)
    assert [p.user_id for p in match.players] == expected


async def test_queues_are_separated_by_mode(mm):
    await mm.join(GAME, "duel", 1, "a", 1000)
    result = await mm.join(GAME, "trio", 2, "b", 1000)
    assert result.match is None
    assert (await mm.status(GAME, "duel", 1)).waiting_count == 1
    assert (await mm.status(GAME, "trio", 2)).waiting_count == 1


# ----- ready -----

async def test_all_ready_starts_game(mm, games_no_db, redis_client, seat_mode):
    mode, seats = seat_mode
    match = (await fill(mm, mode, list(range(1, seats + 1)))).match

    for p in match.players[:-1]:
        pending = await mm.mark_ready(match.match_id, p.user_id)
        assert isinstance(pending, PendingMatch)
        assert next(q for q in pending.players if q.user_id == p.user_id).ready

    state = await mm.mark_ready(match.match_id, match.players[-1].user_id)
    assert isinstance(state, GameState)

    meta = await games_no_db.get_meta(state.game_id)
    assert meta.is_ranked
    assert [(p.seat_no, p.user_id) for p in meta.players] == [
        (p.seat_no, p.user_id) for p in match.players
    ]
    assert await redis_client.get(keys.match(match.match_id)) is None
    for p in match.players:
        assert await redis_client.get(keys.user_activity(p.user_id)) == keys.activity_game(state.game_id)
        assert await redis_client.ttl(keys.user_activity(p.user_id)) == -1


async def test_ready_from_outsider_is_rejected(mm):
    match = (await fill(mm, "duel", [1, 2])).match
    with pytest.raises(MultiplayerError) as exc:
        await mm.mark_ready(match.match_id, 99)
    assert exc.value.code == "not_in_queue"


async def test_ranked_game_is_recorded(games, make_users, session_factory):
    from app.db.repository import GameSessionRepository

    mm = Matchmaking(games={GAME: games}, rng_factory=lambda: random.Random(SEED))
    users = await make_users(2)
    match = (await fill(mm, "duel", users)).match
    for p in match.players:
        result = await mm.mark_ready(match.match_id, p.user_id)

    async with session_factory() as session:
        record = await GameSessionRepository(session).get_by_id(result.game_id)
    assert record.is_ranked is True
    assert record.status == "in_progress"


# ----- 기한 만료 (감지는 스위퍼, 6단계) -----

PAST_DEADLINE_MS = READY_DEADLINE_SEC * 1000

async def test_expire_requeues_only_ready_with_original_time(mm, redis_client, fake_clock):
    match = (await fill(mm, "duel", [1, 2])).match
    ready = match.players[0]
    absent = match.players[1]
    await mm.mark_ready(match.match_id, ready.user_id)
    fake_clock.advance(PAST_DEADLINE_MS)

    result = await mm.expire_match(match.match_id)
    assert result.requeued == [ready.user_id]
    assert result.dropped == [absent.user_id]
    assert result.match is None

    score = await redis_client.zscore(keys.queue(GAME, "duel"), str(ready.user_id))
    assert int(score) == ready.joined_at_ms
    assert await redis_client.get(keys.user_activity(ready.user_id)) == keys.activity_queue(GAME, "duel")
    assert await redis_client.get(keys.user_activity(absent.user_id)) is None
    assert await redis_client.get(keys.match(match.match_id)) is None
    assert await redis_client.zscore(keys.deadlines(GAME), keys.deadline_ready(match.match_id)) is None


async def test_requeued_player_keeps_priority(mm, fake_clock):
    """복귀자는 원래 입장 시각이라 나중에 온 사람보다 앞이다"""
    match = (await fill(mm, "duel", [1, 2])).match
    await mm.mark_ready(match.match_id, match.players[0].user_id)
    await mm.join(GAME, "trio", 3, "c", 1000)  # 다른 큐 — 영향 없음
    await mm.join(GAME, "duel", 4, "d", 1000)  # 만료 전 새 입장자
    fake_clock.advance(PAST_DEADLINE_MS)

    result = await mm.expire_match(match.match_id)
    assert result.match is not None  # 복귀자 + 대기자로 즉시 성사
    assert sorted(p.user_id for p in result.match.players) == sorted([match.players[0].user_id, 4])


async def test_expire_after_start_is_noop(mm, redis_client, fake_clock):
    match = (await fill(mm, "duel", [1, 2])).match
    for p in match.players:
        await mm.mark_ready(match.match_id, p.user_id)
    # 게임이 시작되면 기한 색인도 사라진다
    assert await redis_client.zscore(keys.deadlines(GAME), keys.deadline_ready(match.match_id)) is None
    fake_clock.advance(PAST_DEADLINE_MS)
    result = await mm.expire_match(match.match_id)
    assert (result.requeued, result.dropped, result.match) == ([], [], None)


async def test_match_registers_ready_deadline(mm, redis_client, fake_clock):
    """매치와 기한 색인은 함께 생긴다 — 기한은 주입 시계(Redis TIME) 기준"""
    start = fake_clock.ms
    match = (await fill(mm, "duel", [1, 2])).match
    assert match.ready_deadline_ms == start + PAST_DEADLINE_MS
    score = await redis_client.zscore(keys.deadlines(GAME), keys.deadline_ready(match.match_id))
    assert int(score) == match.ready_deadline_ms


async def test_expire_before_deadline_is_noop_and_reregisters(mm, redis_client, fake_clock):
    """낡은 색인(점수가 과거)으로 불려도 매치 기록의 기한이 판단한다"""
    match = (await fill(mm, "duel", [1, 2])).match
    member = keys.deadline_ready(match.match_id)
    await redis_client.zadd(keys.deadlines(GAME), {member: 0})
    fake_clock.advance(PAST_DEADLINE_MS - 1)

    result = await mm.expire_match(match.match_id)
    assert (result.requeued, result.dropped, result.match) == ([], [], None)
    assert await redis_client.get(keys.match(match.match_id)) is not None
    assert int(await redis_client.zscore(keys.deadlines(GAME), member)) == match.ready_deadline_ms


# ----- MMR 범위 (비활성) -----

def test_mmr_window_table():
    assert mmr_window(0, "duel") == 100
    assert mmr_window(10, "duel") == 200
    assert mmr_window(45, "duel") == 350
    assert mmr_window(60, "duel") == MMR_WINDOW_CAP["duel"]
    assert mmr_window(600, "trio") == MMR_WINDOW_CAP["trio"]
    assert mmr_window(600, "unlisted-mode") == 500


async def test_mmr_filter_is_not_silently_ignored(mm, monkeypatch):
    monkeypatch.setattr(settings, "match_mmr_filter_enabled", True)
    with pytest.raises(NotImplementedError):
        await mm.join(GAME, "duel", 1, "a", 1000)
