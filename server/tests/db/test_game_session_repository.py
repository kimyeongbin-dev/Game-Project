"""
GameSessionRepository Tests
게임 시작·종료 기록 — 좌석 수 2·3·4 로 파라미터화한다.
"인원이 4명이 되면?" → 행만 는다 (docs/api/platform.md §5).
"""

import uuid

import pytest
from sqlalchemy import delete, func, select

from app.db.models import GameParticipant, GameSession
from app.db.repository import GameSessionRepository, ParticipantSeed, SeatResult


@pytest.fixture(params=[2, 3, 4], ids=["2-seats", "3-seats", "4-seats"])
def seats(request) -> int:
    return request.param


def seeds(n: int) -> list[ParticipantSeed]:
    """사람 좌석 N개 (user_id 없이 — users 행에 의존하지 않는다)"""
    return [ParticipantSeed(seat_no=s, user_id=None, display_name=f"p{s}") for s in range(1, n + 1)]


def results_seat1_wins(n: int) -> list[SeatResult]:
    """seat 1 도달, 마지막 좌석 항복, 나머지 생존"""
    out = [SeatResult(seat_no=1, result="win", rank=1, mmr_before=1000, mmr_after=1016)]
    for s in range(2, n + 1):
        reason = "surrender" if s == n else None
        out.append(SeatResult(seat_no=s, result="lose", rank=s, elimination_reason=reason,
                              mmr_before=1000, mmr_after=992))
    return out


async def new_game(repo: GameSessionRepository, n: int, **kwargs) -> GameSession:
    return await repo.create(
        str(uuid.uuid4()),
        game="maze_1p",
        mode=kwargs.pop("mode", "duel"),
        is_ranked=kwargs.pop("is_ranked", True),
        participants=kwargs.pop("participants", seeds(n)),
    )


class TestCreate:
    """게임 시작 기록"""

    async def test_create_and_get(self, repository, seats):
        created = await new_game(repository, seats)

        fetched = await repository.get_by_id(created.game_id)

        assert fetched.game == "maze_1p"
        assert fetched.mode == "duel"
        assert fetched.is_ranked is True
        assert fetched.status == "in_progress"
        assert fetched.started_at is not None
        assert fetched.ended_at is None
        assert [p.seat_no for p in fetched.participants] == list(range(1, seats + 1))
        assert all(p.result is None for p in fetched.participants)

    async def test_participants_returned_in_seat_order(self, repository, seats):
        """입력 순서와 무관하게 seat_no 순"""
        created = await new_game(repository, seats, participants=list(reversed(seeds(seats))))

        assert [p.seat_no for p in created.participants] == list(range(1, seats + 1))

    async def test_ai_seat(self, repository, user_repository):
        user, _ = await user_repository.create("human1", "password123")
        created = await new_game(repository, 2, participants=[
            ParticipantSeed(seat_no=1, user_id=user.id, display_name="human1"),
            ParticipantSeed(seat_no=2, user_id=None, display_name="AI", is_ai=True),
        ])

        human, ai = created.participants
        assert (human.user_id, human.is_ai) == (user.id, False)
        assert (ai.user_id, ai.is_ai) == (None, True)

    @pytest.mark.parametrize("seat_nos", [[0, 1], [1, 1], [1, 3], [2, 3]],
                             ids=["zero", "duplicate", "gap", "not-from-1"])
    async def test_rejects_bad_seat_numbers(self, repository, seat_nos):
        participants = [ParticipantSeed(seat_no=s, user_id=None, display_name="x") for s in seat_nos]

        with pytest.raises(ValueError):
            await new_game(repository, 0, participants=participants)

    async def test_rejects_single_participant(self, repository):
        with pytest.raises(ValueError):
            await new_game(repository, 1)


class TestRecordResult:
    """게임 종료 기록"""

    async def test_record_result(self, repository, seats):
        created = await new_game(repository, seats)

        ended = await repository.record_result(
            created.game_id,
            end_reason="goal_reached",
            winner_seat_no=1,
            turn_count=37,
            results=results_seat1_wins(seats),
        )

        assert ended.status == "finished"
        assert ended.end_reason == "goal_reached"
        assert ended.winner_seat_no == 1
        assert ended.turn_count == 37
        assert ended.ended_at is not None
        by_seat = {p.seat_no: p for p in ended.participants}
        assert (by_seat[1].result, by_seat[1].rank, by_seat[1].mmr_after) == ("win", 1, 1016)
        assert by_seat[seats].elimination_reason == "surrender"
        assert all(by_seat[s].result == "lose" for s in range(2, seats + 1))

    async def test_missing_seat_result(self, repository, seats):
        created = await new_game(repository, seats)

        with pytest.raises(ValueError):
            await repository.record_result(
                created.game_id, end_reason="last_standing", winner_seat_no=1, turn_count=5,
                results=results_seat1_wins(seats)[:-1],
            )

    async def test_extra_seat_result(self, repository, seats):
        created = await new_game(repository, seats)
        extra = SeatResult(seat_no=seats + 1, result="lose", rank=seats + 1)

        with pytest.raises(ValueError):
            await repository.record_result(
                created.game_id, end_reason="last_standing", winner_seat_no=1, turn_count=5,
                results=results_seat1_wins(seats) + [extra],
            )

    async def test_ends_only_once(self, repository):
        created = await new_game(repository, 2)
        kwargs = dict(end_reason="goal_reached", winner_seat_no=1, turn_count=9,
                      results=results_seat1_wins(2))
        await repository.record_result(created.game_id, **kwargs)

        with pytest.raises(ValueError):
            await repository.record_result(created.game_id, **kwargs)

    @pytest.mark.parametrize("override", [
        {"end_reason": "rage_quit"},
        {"end_reason": "server_fault"},   # 무효는 void() 로만
        {"winner_seat_no": 9},
        {"results": [SeatResult(seat_no=1, result="victory", rank=1),
                     SeatResult(seat_no=2, result="lose", rank=2)]},
        {"results": [SeatResult(seat_no=1, result="win", rank=1),
                     SeatResult(seat_no=2, result="lose", rank=2, elimination_reason="bored")]},
    ], ids=["end_reason", "server_fault", "winner_seat_no", "result", "elimination_reason"])
    async def test_rejects_unknown_values(self, repository, override):
        created = await new_game(repository, 2)
        kwargs = dict(end_reason="goal_reached", winner_seat_no=1, turn_count=1,
                      results=results_seat1_wins(2))
        kwargs.update(override)

        with pytest.raises(ValueError):
            await repository.record_result(created.game_id, **kwargs)

        assert (await repository.get_by_id(created.game_id)).status == "in_progress"


class TestVoid:
    """서버 장애 무효 처리 (maze.md §8)"""

    async def test_void(self, repository, seats):
        created = await new_game(repository, seats)

        voided = await repository.void(created.game_id)

        assert voided.status == "void"
        assert voided.end_reason == "server_fault"
        assert voided.winner_seat_no is None
        assert voided.ended_at is not None
        assert all(p.result == "void" for p in voided.participants)
        assert all(p.mmr_before is None and p.mmr_after is None for p in voided.participants)

    async def test_void_after_finish(self, repository):
        created = await new_game(repository, 2)
        await repository.record_result(created.game_id, end_reason="last_standing",
                                       winner_seat_no=2, turn_count=3, results=[
                                           SeatResult(seat_no=1, result="lose", rank=2,
                                                      elimination_reason="time_forfeit"),
                                           SeatResult(seat_no=2, result="win", rank=1),
                                       ])

        with pytest.raises(ValueError):
            await repository.void(created.game_id)


class TestQueries:

    async def test_list_in_progress(self, repository, seats):
        running = await new_game(repository, seats)
        finished = await new_game(repository, seats)
        voided = await new_game(repository, seats)
        await repository.record_result(finished.game_id, end_reason="goal_reached",
                                       winner_seat_no=1, turn_count=8,
                                       results=results_seat1_wins(seats))
        await repository.void(voided.game_id)

        ids = [g.game_id for g in await repository.list_in_progress()]

        assert ids == [running.game_id]

    async def test_unknown_game(self, repository):
        missing = str(uuid.uuid4())

        assert await repository.get_by_id(missing) is None
        assert await repository.void(missing) is None
        assert await repository.record_result(missing, end_reason="goal_reached", winner_seat_no=1,
                                              turn_count=1, results=results_seat1_wins(2)) is None

    async def test_participants_cascade_on_delete(self, repository, async_session, seats):
        created = await new_game(repository, seats)

        await async_session.execute(delete(GameSession).where(GameSession.game_id == created.game_id))
        await async_session.commit()

        count = await async_session.scalar(
            select(func.count()).select_from(GameParticipant)
            .where(GameParticipant.game_id == created.game_id)
        )
        assert count == 0
