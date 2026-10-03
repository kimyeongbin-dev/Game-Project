"""
종료·무효 처리의 견고성 — 독립 검토 H5·M14·M15·M16·L22 (M3 6단계 커밋 6-F2)

종료 처리(activity·DB) 실패가 종료 통지와 결과를 뒤집지 않는지, 닫힌 게임을 다시 쓰지 않는지 본다.
DB 는 쓰지 않는다 — DB 기록 성공·실패는 `_record_result` 를 바꿔 끼워 흉내 낸다.
"""

import random

import pytest

from app.db import redis_keys as keys
from app.db.redis_lock import StoreUnavailable
from app.services import activity as activity_module
from app.services import events
from app.services.matchmaking import Matchmaking
from app.services.maze_game import GAME, MazeGameService, SeatPlayer
from app.services.sweeper import DeadlineSweeper, paged
from app.core.config import settings


class RecordingPublisher:
    def __init__(self):
        self.events: list[events.Event] = []

    async def publish(self, event) -> None:
        self.events.append(event)

    def kinds(self) -> list[str]:
        return [e.kind for e in self.events]


@pytest.fixture
def pub() -> RecordingPublisher:
    return RecordingPublisher()


@pytest.fixture
def games(redis_client, pub, fake_clock) -> MazeGameService:
    return MazeGameService(lambda: None, publisher=pub, clock=fake_clock)


async def start(games, mode="duel", seats=2):
    users = list(range(701, 701 + seats))
    state = await games.create_game(
        mode=mode, is_ranked=False,
        players=[SeatPlayer(i + 1, uid, f"p{uid}") for i, uid in enumerate(users)],
    )
    return state, users


# ----- H5 — 종료 처리 실패가 종료를 뒤집지 않는다 -----

async def test_finish_is_announced_even_if_activity_release_fails(games, pub, monkeypatch):
    state, users = await start(games)

    async def broken(*args, **kwargs):
        raise StoreUnavailable("redis hiccup")

    monkeypatch.setattr(activity_module, "release", broken)
    outcome = await games.surrender(state.game_id, users[0])
    assert outcome.ended
    assert pub.events[-1].kind == events.GAME_UPDATED and pub.events[-1].hint["ended"] is True
    assert (await games.load_game(state.game_id)).is_finished


async def test_meta_gets_finish_ttl_in_the_same_write(games, redis_client):
    state, users = await start(games)
    await games.surrender(state.game_id, users[0])
    state_ttl = await redis_client.ttl(keys.game_state(state.game_id))
    assert state_ttl > 0
    assert abs(await redis_client.ttl(keys.game_meta(state.game_id)) - state_ttl) <= 1


async def test_unrecorded_result_is_retried_not_voided(games, pub, redis_client, fake_clock, monkeypatch):
    """DB 기록이 실패한 승리는 TTL 뒤에도 무효로 뒤집히지 않고, 유실 점검이 기록을 다시 시도한다"""
    state, users = await start(games)
    started_ms = fake_clock.ms
    attempts = []

    async def flaky_record(game_id, record):
        attempts.append(record)
        return len(attempts) > 1          # 첫 시도(종료 직후)는 실패, 재시도는 성공

    monkeypatch.setattr(games, "_record_result", flaky_record)
    await games.surrender(state.game_id, users[0])
    assert await redis_client.get(keys.game_result(state.game_id)) is not None
    assert attempts[0]["end_reason"] == "last_standing" and attempts[0]["winner_seat_no"] == 2

    # state·meta TTL 만료를 흉내 낸다 — 유실 점검이 이 게임을 "Redis 에 없음"으로 본다
    await redis_client.delete(keys.game_state(state.game_id), keys.game_meta(state.game_id))
    voids = []

    async def db_would_void(game_id):   # DB 는 아직 in_progress — 무효 전이를 시도하면 성공해 버린다
        voids.append(game_id)
        return list(users)

    monkeypatch.setattr(games, "_void_record", db_would_void)
    assert await games.void_lost_game(state.game_id) is False
    assert voids == [] and events.GAME_VOIDED not in pub.kinds()

    async def source():
        return [(state.game_id, started_ms)]

    mm = Matchmaking(games={GAME: games}, rng_factory=lambda: random.Random(1), publisher=pub, clock=fake_clock)
    sweeper = DeadlineSweeper(games, mm, fake_clock, in_progress_source=source)
    fake_clock.advance(settings.lost_game_min_age_sec * 1000 + 1000)
    report = await sweeper.tick()
    assert report.voided == []
    assert events.GAME_VOIDED not in pub.kinds()
    assert len(attempts) == 2 and attempts[1] == attempts[0]
    assert await redis_client.get(keys.game_result(state.game_id)) is None


async def test_db_write_happens_outside_the_game_lock(games, redis_client, monkeypatch):
    """M16 — DB 지연이 게임 락 TTL 을 넘기지 않도록 기록은 락을 놓은 뒤"""
    state, users = await start(games)
    lock_held = []

    async def spy(game_id, record):
        lock_held.append(await redis_client.exists(keys.game_lock(game_id)))
        return True

    monkeypatch.setattr(games, "_record_result", spy)
    await games.surrender(state.game_id, users[0])
    assert lock_held == [0]


# ----- M15 — 시계 없는 게임 -----

async def test_game_without_clocks_starts_them_instead_of_freezing(games, redis_client, fake_clock):
    state, users = await start(games)
    await redis_client.delete(keys.game_clocks(state.game_id))
    target = state.get_valid_pawn_moves()[0]
    assert (await games.move(state.game_id, users[0], target.row, target.col)).rejection is None
    assert await redis_client.exists(keys.game_clocks(state.game_id)) == 1
    assert await redis_client.zscore(keys.deadlines(GAME), keys.deadline_clock(state.game_id)) is not None


# ----- L22 — 닫힌 게임은 쓰지 않는다 -----

async def test_closed_game_is_not_rewritten(games, redis_client):
    state, users = await start(games, "trio", 3)
    await games.surrender(state.game_id, users[0])
    await games.surrender(state.game_id, users[1])          # last_standing 종료
    for key in (keys.game_state(state.game_id), keys.game_clocks(state.game_id)):
        await redis_client.expire(key, 100)
    before = await redis_client.get(keys.game_state(state.game_id))

    assert (await games.surrender(state.game_id, users[2])).rejection == "game_already_ended"
    assert await games.mark_disconnected(state.game_id, users[2]) is None
    assert await games.expire(state.game_id) == []
    assert await redis_client.ttl(keys.game_state(state.game_id)) <= 100     # 연장되지 않았다
    assert await redis_client.ttl(keys.game_clocks(state.game_id)) <= 100
    assert await redis_client.get(keys.game_state(state.game_id)) == before


# ----- M14 — 진행 중 게임 전부 -----

async def test_paged_reads_every_page():
    rows = list(range(250))
    calls = []

    async def fetch(limit, offset):
        calls.append((limit, offset))
        return rows[offset:offset + limit]

    assert await paged(fetch, 100) == rows
    assert calls == [(100, 0), (100, 100), (100, 200)]


async def test_paged_exact_multiple_ends_with_empty_page():
    async def fetch(limit, offset):
        return list(range(200))[offset:offset + limit]

    assert len(await paged(fetch, 100)) == 200


async def test_db_in_progress_reads_real_rows_across_pages(session_factory, monkeypatch):
    """유실 점검의 DB 출처를 실제 DB 로 — 페이지를 넘겨 진행 중 행만 전부 (검토 M14·M18-7)

    DB 픽스처는 비싸서 이 경로 하나만 실제로 돈다. 이 테스트가 없던 동안 db_in_progress 는 없는 속성
    (row.id)을 읽고 있었다.
    """
    import uuid

    from app.db.repository import GameSessionRepository, ParticipantSeed
    from app.services import sweeper as sweeper_module

    created = []
    async with session_factory() as session:
        repo = GameSessionRepository(session)
        for _ in range(3):
            gid = str(uuid.uuid4())
            await repo.create(gid, game=GAME, mode="duel", is_ranked=False,
                              participants=[ParticipantSeed(1, None, "a", True), ParticipantSeed(2, None, "b", True)])
            created.append(gid)
        await repo.void(created[1])

    monkeypatch.setattr(sweeper_module, "is_db_available", lambda: True)
    monkeypatch.setattr(sweeper_module, "get_session_factory", lambda: session_factory)
    monkeypatch.setattr(sweeper_module, "IN_PROGRESS_PAGE", 1)
    rows = await sweeper_module.db_in_progress()
    assert sorted(gid for gid, _ in rows) == sorted([created[0], created[2]])
    assert all(isinstance(started, int) and started > 0 for _, started in rows)
