"""
랭크 매치메이킹 — 큐는 Redis ZSET, 매칭은 Lua 한 번으로 원자적이다.

docs/api/games/maze.md §3. 게임 무관하다 — `game` 인자로 큐가 갈리고, 정원은 그 게임
서비스의 `seats(mode)`(미로는 배치 테이블)가 정한다. 인원 수를 이 모듈은 모른다.

흐름: join → (정원 도달 시) 매칭 성사 = PendingMatch → 전원 ready → 게임 생성.
ready 기한 만료 감지는 6단계 스위퍼가 하고, 처리는 `expire_match` 가 한다 — 응답한
쪽만 **원래 입장 시각으로** 큐에 복귀한다.

Phase 1 은 MMR 필터 없이 FIFO 다. 그래서 주기 매칭 루프가 없고 입장할 때마다 매칭을
시도한다. 범위 확장 규칙은 `mmr_window` 로 보존만 한다 (§3 "지우지 말고 비활성화").
"""

import json
import logging
import random
import time
import uuid
from dataclasses import asdict, dataclass, replace
from typing import Callable, Mapping, Optional, Protocol, Sequence, Union

from app.core.config import settings
from app.db import redis_keys as keys
from app.db.redis_lock import LockTimeout, redis_lock, require_redis, store_errors
from app.games.maze import GameState
from app.services import activity
from app.services.activity import MultiplayerError
from app.services.maze_game import GAME as MAZE, GameBusy, SeatPlayer, maze_games

logger = logging.getLogger(__name__)

# 매칭 성사 후 ready 응답 기한 (maze.md §3 `ready_deadline_sec`)
READY_DEADLINE_SEC = 10

# KEYS[1]=큐 ZSET, KEYS[2]=항목 HASH / ARGV[1]=정원
# 정원이 차 있을 때만 가장 오래 기다린 N명을 꺼낸다. 반환: {uid, score, entry, ...}
_POP_MATCH_LUA = """
local n = tonumber(ARGV[1])
if redis.call('ZCARD', KEYS[1]) < n then
    return {}
end
local popped = redis.call('ZPOPMIN', KEYS[1], n)
local out = {}
for i = 1, #popped, 2 do
    local uid = popped[i]
    table.insert(out, uid)
    table.insert(out, popped[i + 1])
    table.insert(out, redis.call('HGET', KEYS[2], uid) or '{}')
    redis.call('HDEL', KEYS[2], uid)
end
return out
"""


class GameService(Protocol):
    """매치메이킹·방이 게임에 요구하는 것"""

    def seats(self, mode: str) -> int: ...

    async def create_game(self, *, mode: str, is_ranked: bool, players: Sequence[SeatPlayer],
                          room_code: Optional[str] = None,
                          rng: Optional[random.Random] = None) -> GameState: ...


@dataclass(frozen=True)
class QueueStatus:
    game: str
    mode: str
    position: int          # 1부터
    waiting_count: int


@dataclass(frozen=True)
class MatchPlayer:
    seat_no: int
    user_id: int
    nickname: str
    mmr: int
    joined_at_ms: int
    ready: bool = False


@dataclass(frozen=True)
class PendingMatch:
    match_id: str
    game: str
    mode: str
    ready_deadline_ms: int
    players: tuple[MatchPlayer, ...]

    def to_json(self) -> str:
        return json.dumps(asdict(self))

    @classmethod
    def from_json(cls, raw: str) -> "PendingMatch":
        data = json.loads(raw)
        data["players"] = tuple(MatchPlayer(**p) for p in data["players"])
        return cls(**data)


@dataclass(frozen=True)
class JoinResult:
    status: QueueStatus
    match: Optional[PendingMatch]   # 이 입장으로 성사된 매치 (입장자가 포함되지 않을 수도 있다)


@dataclass(frozen=True)
class ExpireResult:
    requeued: list[int]             # 응답해서 큐로 돌아간 유저
    dropped: list[int]              # 응답하지 않아 활동이 풀린 유저
    match: Optional[PendingMatch]   # 복귀 직후 새로 성사된 매치


# ----- MMR 범위 (비활성) -----

# (대기 초 미만, 허용 MMR 차) — maze.md §3 표. 마지막 구간 이후는 모드별 상한
MMR_WINDOW_STEPS: tuple[tuple[int, int], ...] = ((10, 100), (30, 200), (60, 350))
MMR_WINDOW_CAP: dict[str, int] = {"duel": 500, "trio": 700}
MMR_WINDOW_CAP_DEFAULT = 500


def mmr_window(wait_sec: float, mode: str) -> int:
    """대기 시간에 따른 허용 MMR 차. Phase 1 은 매칭에 쓰지 않는다 (§3)"""
    for limit, gap in MMR_WINDOW_STEPS:
        if wait_sec < limit:
            return gap
    return MMR_WINDOW_CAP.get(mode, MMR_WINDOW_CAP_DEFAULT)


def _now_ms() -> int:
    return int(time.time() * 1000)


class Matchmaking:
    def __init__(
        self,
        games: Optional[Mapping[str, GameService]] = None,
        rng_factory: Callable[[], random.Random] = random.Random,
    ):
        self._games = dict(games) if games is not None else {MAZE: maze_games}
        self._rng_factory = rng_factory

    def _seats(self, game: str, mode: str) -> int:
        service = self._games.get(game)
        if service is None:
            raise ValueError(f"Unknown game: {game}")
        return service.seats(mode)

    # ----- 큐 -----

    async def join(self, game: str, mode: str, user_id: int, nickname: str, mmr: int) -> JoinResult:
        """큐 입장. 이미 같은 큐면 그대로 둔다. 다른 활동 중이면 MultiplayerError"""
        self._seats(game, mode)  # 없는 게임·모드 거절
        redis = require_redis()
        await activity.claim(redis, user_id, keys.activity_queue(game, mode))

        entry = json.dumps({"nickname": nickname, "mmr": mmr})
        async with store_errors():
            if await redis.zadd(keys.queue(game, mode), {str(user_id): _now_ms()}, nx=True):
                await redis.hset(keys.queue_entries(game, mode), str(user_id), entry)

        match = await self.try_match(game, mode)
        status = await self.status(game, mode, user_id)
        return JoinResult(status=status, match=match)

    async def leave(self, game: str, mode: str, user_id: int) -> None:
        """큐 이탈. 큐에 없으면(이미 매칭됐으면) not_in_queue"""
        redis = require_redis()
        async with store_errors():
            removed = await redis.zrem(keys.queue(game, mode), str(user_id))
            await redis.hdel(keys.queue_entries(game, mode), str(user_id))
        if not removed:
            raise MultiplayerError("not_in_queue")
        await activity.release(redis, user_id, keys.activity_queue(game, mode))

    async def status(self, game: str, mode: str, user_id: int) -> QueueStatus:
        redis = require_redis()
        async with store_errors():
            rank = await redis.zrank(keys.queue(game, mode), str(user_id))
            count = await redis.zcard(keys.queue(game, mode))
        return QueueStatus(game, mode, 0 if rank is None else rank + 1, count)

    # ----- 매칭 -----

    async def try_match(self, game: str, mode: str) -> Optional[PendingMatch]:
        """정원이 차 있으면 가장 오래 기다린 N명으로 매치를 만든다. 좌석은 무작위"""
        if settings.match_mmr_filter_enabled:
            raise NotImplementedError("MMR filter is not wired yet — maze.md §3")
        seats = self._seats(game, mode)
        redis = require_redis()
        async with store_errors():
            flat = await redis.eval(
                _POP_MATCH_LUA, 2, keys.queue(game, mode), keys.queue_entries(game, mode), seats
            )
        if not flat:
            return None

        popped = []
        for i in range(0, len(flat), 3):
            entry = json.loads(flat[i + 2])
            popped.append((int(flat[i]), int(float(flat[i + 1])), entry))
        # 큐에 먼저 들어왔다고 선수(seat 1)를 가져가지 않는다
        self._rng_factory().shuffle(popped)

        match = PendingMatch(
            match_id=str(uuid.uuid4()),
            game=game,
            mode=mode,
            ready_deadline_ms=_now_ms() + READY_DEADLINE_SEC * 1000,
            players=tuple(
                MatchPlayer(
                    seat_no=i + 1,
                    user_id=uid,
                    nickname=entry.get("nickname", ""),
                    mmr=entry.get("mmr", 0),
                    joined_at_ms=joined_at,
                )
                for i, (uid, joined_at, entry) in enumerate(popped)
            ),
        )
        async with store_errors():
            await redis.set(keys.match(match.match_id), match.to_json(), ex=settings.match_record_ttl_sec)
        for p in match.players:
            moved = await activity.transition(
                redis, p.user_id, keys.activity_queue(game, mode), keys.activity_match(match.match_id),
                ttl_sec=settings.match_record_ttl_sec,
            )
            if not moved:
                logger.warning("User %s left activity before match %s", p.user_id, match.match_id)
        return match

    async def mark_ready(self, match_id: str, user_id: int) -> Union[PendingMatch, GameState]:
        """ready 응답. 전원 준비되면 랭크 게임을 만들고 GameState 를 돌려준다"""
        redis = require_redis()
        try:
            async with redis_lock(redis, keys.match_lock(match_id)):
                async with store_errors():
                    raw = await redis.get(keys.match(match_id))
                if raw is None:
                    raise MultiplayerError("not_in_queue")
                match = PendingMatch.from_json(raw)
                if user_id not in {p.user_id for p in match.players}:
                    raise MultiplayerError("not_in_queue")

                match = replace(match, players=tuple(
                    replace(p, ready=True) if p.user_id == user_id else p for p in match.players
                ))
                if not all(p.ready for p in match.players):
                    async with store_errors():
                        await redis.set(keys.match(match_id), match.to_json(), keepttl=True)
                    return match

                state = await self._games[match.game].create_game(
                    mode=match.mode,
                    is_ranked=True,
                    players=[SeatPlayer(p.seat_no, p.user_id, p.nickname) for p in match.players],
                )
                async with store_errors():
                    await redis.delete(keys.match(match_id))
                return state
        except LockTimeout as exc:
            raise GameBusy(str(exc)) from exc

    async def expire_match(self, match_id: str) -> ExpireResult:
        """ready 기한 만료 처리 — 응답한 쪽만 원래 입장 시각으로 큐에 복귀한다 (§3)

        기한 감지는 6단계 스위퍼 몫이다. 이미 게임이 시작됐거나 처리된 매치면 빈 결과.
        """
        redis = require_redis()
        try:
            async with redis_lock(redis, keys.match_lock(match_id)):
                async with store_errors():
                    raw = await redis.get(keys.match(match_id))
                    if raw is None:
                        return ExpireResult([], [], None)
                    await redis.delete(keys.match(match_id))
                match = PendingMatch.from_json(raw)
        except LockTimeout as exc:
            raise GameBusy(str(exc)) from exc

        held = keys.activity_match(match_id)
        requeued, dropped = [], []
        for p in match.players:
            if not p.ready:
                await activity.release(redis, p.user_id, held)
                dropped.append(p.user_id)
                continue
            if not await activity.transition(
                redis, p.user_id, held, keys.activity_queue(match.game, match.mode)
            ):
                continue  # 그 사이 다른 활동으로 옮겨 갔다
            async with store_errors():
                await redis.zadd(keys.queue(match.game, match.mode), {str(p.user_id): p.joined_at_ms})
                await redis.hset(
                    keys.queue_entries(match.game, match.mode), str(p.user_id),
                    json.dumps({"nickname": p.nickname, "mmr": p.mmr}),
                )
            requeued.append(p.user_id)

        new_match = await self.try_match(match.game, match.mode) if requeued else None
        return ExpireResult(requeued, dropped, new_match)


matchmaking = Matchmaking()
