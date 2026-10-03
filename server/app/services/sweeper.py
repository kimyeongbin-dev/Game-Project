"""
데드라인 스위퍼 — 시계 만료·매치 ready 만료·Redis 장애·상태 유실 (maze.md §8, M3 6단계)

워커마다 하나씩 돈다. 리더가 없다.

- **클레임은 지우지 않고 빌린다.** 기한이 지난 member 를 Lua 한 번으로 꺼내면서 점수를
  `now + 리스` 로 미룬다. 같은 리스 창에서 두 워커가 같은 member 를 받지 못한다. 처리 전에
  워커가 죽으면 리스가 끝난 뒤 member 가 다시 나타나 다른 워커가 처리한다
  (§8 의 "ZREM 선점"은 ZREM 직후 크래시면 그 게임이 영원히 만료되지 않는다)
- **정확성은 락 안 재계산이 보장한다.** 처리(`expire`·`expire_match`)는 게임·매치 락 안에서 저장된
  시계·기한으로 다시 판단한다. 이미 처리된 것은 아무 일도 없고, 점수만 낡았으면 올바른 점수로 다시 적힌다
- **Redis 장애 구간을 기록한다.** Redis 호출이 실패한 회차가 있었을 때만(워커 정지와 구분) 복구 후
  `[마지막 성공 + 첫 실패까지의 단조 시간, 복구 시각]` 을 `store:outages` 에 적는다. 이 구간은 두 시계에서
  빠진다. `store_outage_void_sec` 이상이면 그 전에 시작한 진행 중 게임을 무효로 닫는다
- **상태 유실을 점검한다.** DB 에 진행 중인데 Redis state 가 없는 게임을 `void_lost_game` 으로 닫는다.
  Redis 가 통째로 비면 ZSET 도 사라지므로 출처는 DB 다. 생성 직후(DB 먼저 → Redis) 오탐을 피하려고
  `lost_game_min_age_sec` 보다 오래된 것만 본다. 점검 락으로 주기마다 한 워커만 한다

lifespan 배선(start/stop)은 7단계다. 프로세스 로컬 상태는 루프 태스크와 장애 관측뿐이다.
"""

import asyncio
import logging
import secrets
import time
from dataclasses import dataclass, field
from datetime import timezone
from typing import Awaitable, Callable, Optional

from redis.exceptions import RedisError

from app.core.config import settings
from app.core.time import Clock, redis_clock
from app.db import redis_keys as keys
from app.db.config import get_session_factory, is_db_available
from app.db.redis_lock import StoreUnavailable, require_redis, store_errors
from app.db.repository import GameSessionRepository
from app.services import outages
from app.services.matchmaking import Matchmaking, matchmaking
from app.services.maze_game import (
    GAME,
    GameBusy,
    GameNotFound,
    MazeGameService,
    StateVersionMismatch,
    maze_games,
)

logger = logging.getLogger(__name__)

# KEYS[1]=deadlines / ARGV[1]=now, ARGV[2]=리스 끝, ARGV[3]=최대 개수
# 꺼낸 member 의 점수를 리스 끝으로 미룬다 — 꺼내기와 미루기가 원자적이다
_CLAIM_LUA = """
local due = redis.call('ZRANGEBYSCORE', KEYS[1], '-inf', ARGV[1], 'LIMIT', 0, tonumber(ARGV[3]))
for _, m in ipairs(due) do
    redis.call('ZADD', KEYS[1], 'XX', ARGV[2], m)
end
return due
"""

# (game_id, 시작 epoch ms) — DB 에 진행 중으로 기록된 게임
InProgressSource = Callable[[], Awaitable[list[tuple[str, int]]]]


async def db_in_progress() -> list[tuple[str, int]]:
    """앱 DB 의 진행 중 게임. DB 를 쓸 수 없으면 빈 목록"""
    if not is_db_available():
        return []
    async with get_session_factory()() as session:
        rows = await GameSessionRepository(session).list_in_progress()
    return [
        (row.id, int(row.started_at.replace(tzinfo=timezone.utc).timestamp() * 1000))
        for row in rows
    ]


@dataclass
class TickReport:
    """한 회차의 결과 — 테스트와 로그용"""
    ok: bool = True
    claimed: list[str] = field(default_factory=list)
    expired: list[tuple[str, int, str]] = field(default_factory=list)   # (game_id, seat_no, reason)
    outage: Optional[tuple[int, int]] = None
    voided: list[str] = field(default_factory=list)


class DeadlineSweeper:
    def __init__(
        self,
        games: MazeGameService = maze_games,
        matches: Matchmaking = matchmaking,
        clock: Clock = redis_clock,
        *,
        game: str = GAME,
        in_progress_source: InProgressSource = db_in_progress,
        monotonic: Callable[[], float] = time.monotonic,
    ):
        self._games = games
        self._matches = matches
        self._clock = clock
        self._game = game
        self._in_progress = in_progress_source
        self._monotonic = monotonic
        # 장애 관측 — 마지막 성공(Redis 시각 + 단조 시각), 그 뒤 첫 실패(단조 시각)
        self._last_ok_ms: Optional[int] = None
        self._last_ok_mono: Optional[float] = None
        self._first_fail_mono: Optional[float] = None
        self._next_scan_ms: Optional[int] = None
        self._task: Optional[asyncio.Task] = None

    # ----- 루프 (7단계 lifespan 이 부른다) -----

    async def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._loop(), name="deadline-sweeper")

    async def stop(self) -> None:
        if self._task is None:
            return
        self._task.cancel()
        try:
            await self._task
        except asyncio.CancelledError:
            pass
        self._task = None

    async def _loop(self) -> None:
        while True:
            try:
                await self.tick()
            except asyncio.CancelledError:
                raise
            except Exception:  # 루프는 죽지 않는다
                logger.exception("Sweeper tick failed")
            await asyncio.sleep(settings.sweeper_interval_ms / 1000)

    # ----- 한 회차 -----

    async def tick(self) -> TickReport:
        report = TickReport()
        try:
            now = await self._clock.now_ms()
            report.outage = await self._observe_recovery(now, report)
            report.claimed = await self.claim(now)
            for member in report.claimed:
                await self._process(member, report)
            await self._scan_lost(now, report)
            self._mark_ok(now)
        except (StoreUnavailable, RedisError) as exc:
            report.ok = False
            self._mark_failure()
            logger.warning("Sweeper sees store failure: %s", exc)
        return report

    async def claim(self, now: int) -> list[str]:
        """기한이 지난 member 를 빌린다 — 같은 리스 창에서 다른 워커는 받지 못한다"""
        redis = require_redis()
        async with store_errors():
            return list(await redis.eval(
                _CLAIM_LUA, 1, keys.deadlines(self._game),
                now, now + settings.sweeper_claim_lease_ms, settings.sweeper_batch,
            ))

    async def _process(self, member: str, report: TickReport) -> None:
        kind, target = keys.parse_deadline(member)
        try:
            if kind in (keys.DEADLINE_CLOCK, keys.DEADLINE_GRACE):
                for seat_no, reason in await self._games.expire(target):
                    report.expired.append((target, seat_no, reason))
            elif kind == keys.DEADLINE_READY:
                await self._matches.expire_match(target)
                await self._drop_if_gone(member, keys.match(target))
            else:
                logger.warning("Unknown deadline member %s — removed", member)
                await self._drop(member)
        except GameNotFound:
            # 상태가 없다 — 끝난 지 오래됐거나 유실. 유실 판정은 _scan_lost 몫이다
            await self._drop(member)
        except GameBusy:
            logger.info("Deadline %s busy — retried after lease", member)
        except StateVersionMismatch:
            logger.error("Deadline %s has incompatible state — left for operator", member)
        except (StoreUnavailable, RedisError):
            raise
        except Exception:
            logger.exception("Deadline %s failed — retried after lease", member)

    async def _drop(self, member: str) -> None:
        async with store_errors():
            await require_redis().zrem(keys.deadlines(self._game), member)

    async def _drop_if_gone(self, member: str, target_key: str) -> None:
        redis = require_redis()
        async with store_errors():
            if not await redis.exists(target_key):
                await redis.zrem(keys.deadlines(self._game), member)

    # ----- Redis 장애 (판단 8) -----

    def _mark_failure(self) -> None:
        if self._first_fail_mono is None:
            self._first_fail_mono = self._monotonic()

    def _mark_ok(self, now: int) -> None:
        self._last_ok_ms = now
        self._last_ok_mono = self._monotonic()
        self._first_fail_mono = None

    async def _observe_recovery(self, now: int, report: TickReport) -> Optional[tuple[int, int]]:
        """실패 뒤 첫 성공이면 장애 구간을 기록하고, 길면 진행 중 게임을 무효로 닫는다"""
        if self._first_fail_mono is None or self._last_ok_ms is None:
            return None
        gap_ms = int((self._first_fail_mono - self._last_ok_mono) * 1000)
        start = self._last_ok_ms + max(0, gap_ms)
        if now - start < settings.store_outage_min_ms:
            return None
        await outages.record(require_redis(), start, now,
                             retention_ms=settings.outage_retention_sec * 1000)
        logger.warning("Recorded store outage %d..%d (%d ms)", start, now, now - start)
        if now - start >= settings.store_outage_void_sec * 1000:
            report.voided += await self._void_running(started_before_ms=now)
        return start, now

    async def _void_running(self, *, started_before_ms: int) -> list[str]:
        """진행 중 게임 = 데드라인 색인의 clock: member 전부 (게임당 하나)"""
        redis = require_redis()
        async with store_errors():
            members = await redis.zrange(keys.deadlines(self._game), 0, -1)
        voided = []
        for member in members:
            kind, game_id = keys.parse_deadline(member)
            if kind != keys.DEADLINE_CLOCK:
                continue
            try:
                if await self._games.void_game(game_id, started_before_ms=started_before_ms):
                    voided.append(game_id)
            except GameBusy:
                logger.warning("Game %s busy — void retried by the next outage observer", game_id)
        return voided

    # ----- 상태 유실 (판단 8) -----

    async def _scan_lost(self, now: int, report: TickReport) -> None:
        if self._next_scan_ms is not None and now < self._next_scan_ms:
            return
        interval_ms = settings.lost_scan_interval_sec * 1000
        self._next_scan_ms = now + interval_ms
        redis = require_redis()
        async with store_errors():
            # 주기마다 한 워커만 — 풀지 않고 만료되게 둔다
            if not await redis.set(keys.deadlines_scan_lock(self._game), secrets.token_hex(8),
                                   nx=True, px=interval_ms):
                return
        try:
            rows = await self._in_progress()
        except Exception:
            logger.exception("Lost-state scan could not read in-progress games")
            return
        min_age_ms = settings.lost_game_min_age_sec * 1000
        for game_id, started_ms in rows:
            if now - started_ms < min_age_ms:
                continue  # 생성 중일 수 있다 — DB 를 먼저 쓰고 Redis 에 쓴다
            async with store_errors():
                present = await redis.exists(keys.game_state(game_id))
            if present:
                continue
            try:
                if await self._games.void_lost_game(game_id):
                    report.voided.append(game_id)
            except GameBusy:
                logger.warning("Game %s busy — lost-state void retried next scan", game_id)
