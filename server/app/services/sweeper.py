"""
데드라인 스위퍼 — 시계 만료·매치 ready 만료·Redis 장애·상태 유실 (maze.md §8, M3 6단계)

워커마다 하나씩 돈다. 리더가 없다.

- **클레임은 지우지 않고 빌린다.** 기한이 지난 member 를 Lua 한 번으로 꺼내면서 점수를
  `now + 리스` 로 미룬다. 같은 리스 창에서 두 워커가 같은 member 를 받지 못한다. 처리 전에
  워커가 죽으면 리스가 끝난 뒤 member 가 다시 나타나 다른 워커가 처리한다
  (§8 의 "ZREM 선점"은 ZREM 직후 크래시면 그 게임이 영원히 만료되지 않는다)
- **정확성은 락 안 재계산이 보장한다.** 처리(`expire`·`expire_match`)는 게임·매치 락 안에서 저장된
  시계·기한으로 다시 판단한다. 이미 처리된 것은 아무 일도 없고, 점수만 낡았으면 올바른 점수로 다시 적힌다
- **전역 하트비트를 갱신한다.** 전용 루프(200 ms, `_alive_loop`)와 회차마다 `store:alive` 를 지금 시각으로 바꾸고, 직전 값과의 공백이 하한
  이상이면 그 구간을 `store:outages` 에 적는다(app/services/outages.py, Lua 한 번). 어느 워커든 성공하면
  갱신되므로 공백은 **전역** 장애(또는 전 워커 정지)뿐이고, 관측 상태가 Redis 안에 있어 재기동해도 잃지 않는다.
  구간이 `store_outage_void_sec` 이상이면 **장애 시작 전에** 시작한 진행 중 게임을 무효로 닫는다. 이 회차에
  닫지 못한 게임은 다음 처리 때 스스로 닫힌다(maze_game `_void_due`)
- **상태 유실을 점검한다.** DB 에 진행 중인데 Redis state 가 없는 게임을 `void_lost_game` 으로 닫는다.
  Redis 가 통째로 비면 ZSET 도 사라지므로 출처는 DB 다. 생성 직후(DB 먼저 → Redis) 오탐을 피하려고
  `lost_game_min_age_sec` 보다 오래된 것만 본다. 점검 락으로 주기마다 한 워커만 한다

lifespan 배선(start/stop)은 `app/ws/runtime.py`(M3 7단계). 프로세스 로컬 상태는 루프 태스크와 장애 관측뿐이다.
"""

import asyncio
import logging
import secrets
from dataclasses import dataclass, field
from datetime import timezone
from typing import Awaitable, Callable, Optional

from redis.exceptions import RedisError

from app.core.config import settings
from app.core.time import Clock, redis_clock
from app.core.worker import WORKER_ID
from app.db import redis_keys as keys
from app.db.config import get_session_factory, is_db_available
from app.db.redis import HeartbeatConnection
from app.db.redis_lock import StoreUnavailable, require_redis, store_errors
from app.db.repository import GameSessionRepository
from app.services import outages
from app.services.outages import void_boundary
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

# KEYS[1]=workers / ARGV[1]=하트비트가 이보다 이르면 죽음, ARGV[2]=리스 끝 점수, ARGV[3]=최대 개수
# 죽은 워커를 꺼내며 점수를 미룬다(처리 전에 죽으면 리스 뒤 재등장). 반환: {id, 마지막 하트비트, ...}
_CLAIM_WORKERS_LUA = """
local dead = redis.call('ZRANGEBYSCORE', KEYS[1], '-inf', '(' .. ARGV[1], 'WITHSCORES', 'LIMIT', 0, tonumber(ARGV[3]))
for i = 1, #dead, 2 do
    redis.call('ZADD', KEYS[1], 'XX', ARGV[2], dead[i])
end
return dead
"""

# KEYS[1]=workers, KEYS[2]=그 워커의 좌석 색인 / ARGV[1]=워커 id, ARGV[2]=클레임한 점수
# 좌석을 다 처리했고 그 사이 워커가 되살아나지 않았으면(점수 그대로) 지운다
_FORGET_WORKER_LUA = """
if redis.call('ZCARD', KEYS[2]) == 0 and redis.call('ZSCORE', KEYS[1], ARGV[1]) == ARGV[2] then
    redis.call('ZREM', KEYS[1], ARGV[1])
    return 1
end
return 0
"""

# (game_id, 시작 epoch ms) — DB 에 진행 중으로 기록된 게임
InProgressSource = Callable[[], Awaitable[list[tuple[str, int]]]]


IN_PROGRESS_PAGE = 100
# 긴 장애 기록을 훑는 범위 — 기록 직후 몇 회차 안에 처리된다. 그보다 오래된 기록은 이미 처리됐다
LONG_OUTAGE_SCAN_MS = 600_000
# 전용 하트비트가 이만큼 연속 실패하면 경고한다(200 ms × 25 ≈ 5 s — 짧은 재시작은 조용히 넘긴다)
HEARTBEAT_WARN_AFTER = 25


async def paged(fetch_page: Callable[[int, int], Awaitable[list]], page_size: int = IN_PROGRESS_PAGE) -> list:
    """페이지를 끝까지 넘긴다 — 진행 중 게임이 몇 개든 전부 본다(검토 M14)"""
    out: list = []
    offset = 0
    while True:
        page = await fetch_page(page_size, offset)
        out.extend(page)
        if len(page) < page_size:
            return out
        offset += page_size


async def db_in_progress() -> list[tuple[str, int]]:
    """앱 DB 의 진행 중 게임 전부. DB 를 쓸 수 없으면 빈 목록"""
    if not is_db_available():
        return []

    async def fetch(limit: int, offset: int) -> list:
        async with get_session_factory()() as session:
            return await GameSessionRepository(session).list_in_progress(limit=limit, offset=offset)

    return [
        (row.game_id, int(row.started_at.replace(tzinfo=timezone.utc).timestamp() * 1000))
        for row in await paged(fetch, IN_PROGRESS_PAGE)
    ]


@dataclass
class TickReport:
    """한 회차의 결과 — 테스트와 로그용"""
    ok: bool = True
    claimed: list[str] = field(default_factory=list)
    expired: list[tuple[str, int, str]] = field(default_factory=list)   # (game_id, seat_no, reason)
    dropped: list[tuple[str, int]] = field(default_factory=list)          # 죽은 워커의 좌석 → 끊김
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
        worker_id: str = WORKER_ID,
    ):
        self._games = games
        self._matches = matches
        self._clock = clock
        self._game = game
        self._in_progress = in_progress_source
        self._worker_id = worker_id
        self._next_scan_ms: Optional[int] = None
        self._voided_outages: set[str] = set()
        self._task: Optional[asyncio.Task] = None
        self._alive_task: Optional[asyncio.Task] = None
        # 관측용 — /health 가 보고한다
        self.last_tick_ok: Optional[bool] = None
        self.last_tick_at_ms: Optional[int] = None

    @property
    def running(self) -> bool:
        return self._task is not None and not self._task.done()

    # ----- 루프 (app/ws/runtime.py 가 lifespan 에서 부른다) -----

    async def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._loop(), name="deadline-sweeper")
        # 전역 하트비트는 Redis TIME 으로 찍는다 — 시계를 주입한 테스트(가짜 시각)와 섞지 않는다
        if self._alive_task is None and self._clock is redis_clock:
            self._alive_task = asyncio.create_task(self._alive_loop(), name="store-heartbeat")

    async def stop(self) -> None:
        # 둘 다 먼저 취소하고 함께 기다린다. stop 자신의 취소는 삼키지 않는다(예전 except CancelledError 가 삼켰다 — 검토 #3)
        tasks = [t for t in (self._task, self._alive_task) if t is not None]
        self._task = self._alive_task = None
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    async def _alive_loop(self) -> None:
        """전역 하트비트만 짧은 주기로 — 회차(만료 처리·사망 판정)와 떼어 둔다

        회차에 묶으면 장애 시작 추정이 최대 회차 주기만큼 이르고, 복구 뒤 첫 회차가 앱 풀의 긴 타임아웃에 걸려 장애 끝이
        늦게 찍힌다(실측 S5: ≈1.9 s 재시작이 3.0~4.9 s 로, 10.3 s 정지가 12.8 s 로). 전용 연결·짧은 타임아웃·스크립트 안
        시각으로 양 끝 오차를 이 주기 단위로 줄인다. 공백 기록·긴 장애 무효는 같은 Lua 라 회차의 `_heartbeat` 와 겹쳐도
        한 번만 일어난다(무효 훑기는 회차가 한다).
        """
        conn = HeartbeatConnection()
        failures = 0
        try:
            while True:
                try:
                    client = await conn.client()
                    if client is not None:
                        outage = await outages.beat(client, min_ms=settings.store_outage_min_ms,
                                                    retention_ms=settings.outage_retention_sec * 1000)
                        if outage is not None:
                            logger.warning("Recorded store outage %d..%d (%d ms)",
                                           outage[0], outage[1], outage[1] - outage[0])
                        if failures >= HEARTBEAT_WARN_AFTER:
                            logger.warning("Store heartbeat recovered after %d failures", failures)
                        failures = 0
                except asyncio.CancelledError:
                    raise
                except Exception as exc:  # 장애 중 — 다음 주기에 다시. 주소가 바뀌었을 수 있다
                    failures += 1
                    # 계속 실패하면 조용히 두지 않는다 — 회차 하트비트(1 s)로 퇴행해 장애 양 끝이 다시 어긋난다(검토 #3, TLS 등)
                    log = logger.warning if failures == HEARTBEAT_WARN_AFTER else logger.debug
                    log("Store heartbeat failed (%d in a row, address %s): %s", failures, conn.address, exc)
                    conn.failed()
                await asyncio.sleep(settings.store_heartbeat_interval_ms / 1000)
        finally:
            await conn.aclose()

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
            report.outage = await self._heartbeat(now, report)
            await self._reap_dead_workers(now, report)
            report.claimed = await self.claim(now)
            for member in report.claimed:
                await self._process(member, report)
            await self._scan_lost(now, report)
        except (StoreUnavailable, RedisError) as exc:
            report.ok = False
            logger.warning("Sweeper sees store failure: %s", exc)
        self.last_tick_ok = report.ok
        if report.ok:
            self.last_tick_at_ms = now
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

    async def _heartbeat(self, now: int, report: TickReport) -> Optional[tuple[int, int]]:
        """전역 하트비트 갱신. 공백이 기록됐고 길면 그 전에 시작한 진행 중 게임을 무효로 닫는다"""
        outage = await outages.heartbeat(
            require_redis(), now,
            min_ms=settings.store_outage_min_ms, retention_ms=settings.outage_retention_sec * 1000,
        )
        if outage is not None:
            logger.warning("Recorded store outage %d..%d (%d ms)", outage[0], outage[1], outage[1] - outage[0])
        # 긴 장애는 누가 기록했든(이 스위퍼든, 복구 뒤 첫 게임 처리든 — 독립 검토 #2 Q4) 한 번씩 그 전에 시작한 게임을 닫는다.
        # 처리한 구간은 이 프로세스가 기억한다 — 재기동하면 다시 훑지만 무효는 멱등이다
        void_ms = settings.store_outage_void_sec * 1000
        async with store_errors():
            recent = await require_redis().zrangebyscore(keys.store_outages(), now - LONG_OUTAGE_SCAN_MS, "+inf")
        for member in recent:
            start, end = outages._parse(member)
            if end - start >= void_ms and member not in self._voided_outages:
                report.voided += await self._void_running(started_before_ms=void_boundary(start))
                self._voided_outages.add(member)
        return outage

    async def _reap_dead_workers(self, now: int, report: TickReport) -> None:
        """내 하트비트를 남기고, 하트비트가 끊긴 워커가 가진 좌석을 끊김으로 처리한다 (검토 H4)

        크래시한 워커의 끊김 핸들러는 아무것도 하지 못한다. 그 좌석은 시계상 "연결 중"으로 남아 접속 시계가
        흐르지 않는다. 그 워커의 마지막 하트비트 시각부터 끊긴 것으로 본다.
        """
        redis = require_redis()
        timeout = settings.worker_heartbeat_timeout_ms
        lease_score = now - timeout + settings.sweeper_claim_lease_ms
        async with store_errors():
            await redis.zadd(keys.workers(), {self._worker_id: now})
            # 전역 Redis 장애 동안에는 **모든** 워커의 하트비트가 멈춘다. 복구 직후 먼저 돈 워커가 살아 있는 다른 워커를 죽었다고
            # 보면, 그 워커의 좌석이 장애 시작부터 끊김이 되어 접속 예산을 넘겨 기권패한다(M3 7단계 다중 워커 실측).
            # 장애가 끝난 뒤 하트비트 타임아웃만큼은 판정하지 않는다 — 그동안 살아 있는 워커는 하트비트를 다시 남긴다
            last_outage = await redis.zrevrange(keys.store_outages(), 0, 0, withscores=True)
        # 창 = 하트비트 타임아웃 + 장애 중 걸린 명령이 끝나는 최장(socket_timeout × (1 + 재시도 1)) + 스위퍼 주기 —
        # 복구 뒤 늦게 회복하는 워커도 그 안에 하트비트를 다시 남긴다(독립 검토 #2 Q6)
        settle = timeout + int(2 * settings.redis_socket_timeout * 1000) + settings.sweeper_interval_ms
        if last_outage and now - int(last_outage[0][1]) < settle:
            return
        async with store_errors():
            flat = await redis.eval(_CLAIM_WORKERS_LUA, 1, keys.workers(),
                                    now - timeout, lease_score, settings.sweeper_batch)
        for i in range(0, len(flat), 2):
            worker, last_beat = flat[i], int(float(flat[i + 1]))
            if worker == self._worker_id:
                continue
            async with store_errors():
                members = await redis.zrange(keys.worker_seats(worker), 0, -1)
            for member in members:
                game_id, seat_no = keys.parse_seat_member(member)
                try:
                    if await self._games.drop_seat(game_id, seat_no, owner=worker, at_ms=last_beat):
                        report.dropped.append((game_id, seat_no))
                    else:  # 이미 다른 워커로 옮겼거나 끝난 좌석 — 색인에서만 지운다
                        async with store_errors():
                            await redis.zrem(keys.worker_seats(worker), member)
                except GameNotFound:
                    async with store_errors():
                        await redis.zrem(keys.worker_seats(worker), member)
                except GameBusy:
                    logger.info("Seat %s of dead worker %s busy — retried after lease", member, worker)
            async with store_errors():
                await redis.eval(_FORGET_WORKER_LUA, 2, keys.workers(), keys.worker_seats(worker),
                                 worker, lease_score)

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
            except (GameBusy, GameNotFound):
                # 바쁜 게임은 다음 처리 때 스스로 닫힌다(_void_due)
                logger.warning("Game %s not voided by sweeper — it voids itself on its next run", game_id)
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
            # 끝났는데 DB 기록만 실패한 게임 — 무효가 아니라 기록 재시도(검토 H5)
            if await self._games.retry_result(game_id) is not None:
                continue
            try:
                if await self._games.void_lost_game(game_id):
                    report.voided.append(game_id)
            except GameBusy:
                logger.warning("Game %s busy — lost-state void retried next scan", game_id)
