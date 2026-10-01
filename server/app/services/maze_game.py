"""
1인칭 미로 게임 서비스 — 진행 중 상태(Redis 권위) + 종료 기록(PostgreSQL).

docs/api/games/maze.md §8: 게임 상태의 권위는 Redis `game:<id>:state` 다. 워커는 상태를
소유하지 않는다. 어느 워커든 행동을 받으면 게임별 락을 잡고 상태를 읽어 판정하고,
락 토큰으로 펜싱해 기록한다. 그래서 워커가 죽거나 교체되어도 게임이 이어진다.

- 엔진(`app.games.maze`)은 저장소·유저를 모른다. 유저 ↔ 좌석 매핑은 `game:<id>:meta` 몫이다
- 시작 시 DB 에 진행 중 행을 먼저 쓴다. §8 fail-safe 는 "DB 에는 진행 중인데 Redis 상태가
  없다"를 유실 판정 기준으로 쓴다
- 상태를 쓴 직후(락 안에서) 이벤트를 발행만 한다(`app/services/events.py`). 소켓 전송은 ws 계층
  구독 버스가 한다. 거절은 발행하지 않는다 — 행동한 사람에게만 응답한다(핸들러, 7단계)
"""

import json
import logging
import random
from dataclasses import asdict, dataclass
from typing import Callable, Optional, Sequence

from sqlalchemy.ext.asyncio import async_sessionmaker

from app.core.config import settings
from app.core.time import utcnow
from app.db import redis_keys as keys
from app.db.config import get_session_factory, is_db_available
from app.db.redis_lock import (
    LockTimeout,
    fenced_set,
    redis_lock,
    require_redis,
    store_errors,
)
from app.db.repository import GameSessionRepository, ParticipantSeed, SeatResult
from app.games.maze import GameState
from app.games.maze.core.game_state import SCHEMA_VERSION
from app.games.maze.core.layouts import get_layout
from app.services import activity, events
from app.services.activity import MultiplayerError
from app.services.events import Publisher, redis_publisher

logger = logging.getLogger(__name__)

GAME = "maze_1p"


class GameNotFound(Exception):
    """Redis 에 그 게임의 상태가 없다 (종료 후 TTL 만료 또는 유실)"""


class StateVersionMismatch(Exception):
    """저장된 state 의 schema_version 이 이 워커와 다르다 — 복원을 거부한다"""


class GameBusy(Exception):
    """게임 락을 대기 상한 안에 얻지 못했거나, 처리 중 락을 잃었다"""


@dataclass(frozen=True)
class SeatPlayer:
    """좌석 하나의 참가자. AI 좌석은 user_id 가 없다"""
    seat_no: int
    user_id: Optional[int]
    nickname: str
    is_ai: bool = False


@dataclass(frozen=True)
class GameMeta:
    """생성 후 불변. 락 없이 읽어도 된다"""
    game_id: str
    game: str
    mode: str
    is_ranked: bool
    room_code: Optional[str]
    created_at: str
    players: tuple[SeatPlayer, ...]

    def seat_of(self, user_id: int) -> Optional[int]:
        for p in self.players:
            if p.user_id is not None and p.user_id == user_id:
                return p.seat_no
        return None

    @property
    def human_user_ids(self) -> list[int]:
        return [p.user_id for p in self.players if p.user_id is not None]

    def to_json(self) -> str:
        return json.dumps(asdict(self))

    @classmethod
    def from_json(cls, raw: str) -> "GameMeta":
        data = json.loads(raw)
        data["players"] = tuple(SeatPlayer(**p) for p in data["players"])
        return cls(**data)


@dataclass(frozen=True)
class ActionOutcome:
    rejection: Optional[str]   # §13 코드. 수락이면 None
    state: GameState
    ended: bool                # 이 행동으로 게임이 끝났다


SessionFactoryProvider = Callable[[], Optional[async_sessionmaker]]


def _app_session_factory() -> Optional[async_sessionmaker]:
    """앱 DB. 사용 불가면 None — 기록 없이 게임은 진행한다 (graceful degradation)"""
    return get_session_factory() if is_db_available() else None


def _decode_state(raw: str) -> GameState:
    data = json.loads(raw)
    if data.get("schema_version") != SCHEMA_VERSION:
        raise StateVersionMismatch(
            f"stored schema_version {data.get('schema_version')} != {SCHEMA_VERSION}"
        )
    return GameState.from_dict(data)


def seat_results(state: GameState) -> list[SeatResult]:
    """엔진 standings() → DB 좌석 결과

    rank 1 은 항상 단독이다(목표 도달자 또는 마지막 생존자). MMR 은 인증·MMR 작업 몫이라 비운다.
    """
    return [
        SeatResult(
            seat_no=s["seat_no"],
            result="win" if s["rank"] == 1 else "lose",
            rank=s["rank"],
            elimination_reason=state.seat(s["seat_no"]).elimination_reason,
        )
        for s in state.standings()
    ]


class MazeGameService:
    """상태는 Redis·DB 에만 있다. 인스턴스는 의존성(DB 세션 팩토리)만 들고 있다"""

    def __init__(
        self,
        session_factory: SessionFactoryProvider = _app_session_factory,
        publisher: Publisher = redis_publisher,
    ):
        self._session_factory = session_factory
        self._publisher = publisher

    # ----- 생성·조회 -----

    @staticmethod
    def seats(mode: str) -> int:
        """모드 정원 — 배치 테이블이 유일한 출처. 없는 모드면 ValueError"""
        return get_layout(mode).seats

    async def create_game(
        self,
        *,
        mode: str,
        is_ranked: bool,
        players: Sequence[SeatPlayer],
        room_code: Optional[str] = None,
        rng: Optional[random.Random] = None,
    ) -> GameState:
        """게임 시작. 좌석은 배치 테이블 정원 1..N 을 정확히 채워야 한다

        사람 좌석의 activity 를 game:<id> 로 덮어쓴다. 호출자(매치·방)가 그 유저들의
        이전 활동을 쥐고 있는 상태에서 부른다.
        """
        seats = self.seats(mode)
        if sorted(p.seat_no for p in players) != list(range(1, seats + 1)):
            raise ValueError(f"mode {mode} needs seats 1..{seats}, got {[p.seat_no for p in players]}")

        redis = require_redis()
        state = GameState(mode, rng=rng)
        meta = GameMeta(
            game_id=state.game_id,
            game=GAME,
            mode=mode,
            is_ranked=is_ranked,
            room_code=room_code,
            created_at=utcnow().isoformat() + "Z",
            players=tuple(sorted(players, key=lambda p: p.seat_no)),
        )

        factory = self._session_factory()
        if factory is not None:
            async with factory() as session:
                await GameSessionRepository(session).create(
                    state.game_id,
                    game=GAME,
                    mode=mode,
                    is_ranked=is_ranked,
                    participants=[
                        ParticipantSeed(p.seat_no, p.user_id, p.nickname, p.is_ai)
                        for p in meta.players
                    ],
                )

        try:
            async with store_errors():
                async with redis.pipeline(transaction=True) as pipe:
                    pipe.set(keys.game_state(state.game_id), json.dumps(state.to_dict()))
                    pipe.set(keys.game_meta(state.game_id), meta.to_json())
                    for user_id in meta.human_user_ids:
                        pipe.set(keys.user_activity(user_id), keys.activity_game(state.game_id))
                    await pipe.execute()
        except Exception:
            # Redis 에 상태가 없으면 이 게임은 진행할 수 없다 — DB 행을 무효로 닫는다
            await self._void_record(state.game_id)
            raise
        await self._publisher.publish(events.game_started(meta))
        return state

    async def load_game(self, game_id: str) -> Optional[GameState]:
        """현재 상태 (락 없이 읽는 스냅샷). 없으면 None, 버전이 다르면 StateVersionMismatch"""
        redis = require_redis()
        async with store_errors():
            raw = await redis.get(keys.game_state(game_id))
        return _decode_state(raw) if raw is not None else None

    async def get_meta(self, game_id: str) -> Optional[GameMeta]:
        redis = require_redis()
        async with store_errors():
            raw = await redis.get(keys.game_meta(game_id))
        return GameMeta.from_json(raw) if raw is not None else None

    # ----- 행동 -----

    async def move(self, game_id: str, user_id: int, row: int, col: int) -> ActionOutcome:
        return await self._act(
            game_id, user_id, events.ACTION_MOVE, lambda s, seat: s.move(seat, row, col)
        )

    async def place_wall(
        self, game_id: str, user_id: int, row: int, col: int, orientation: str
    ) -> ActionOutcome:
        return await self._act(
            game_id, user_id, events.ACTION_WALL,
            lambda s, seat: s.place_wall(seat, row, col, orientation),
        )

    async def surrender(self, game_id: str, user_id: int) -> ActionOutcome:
        """즉시 탈락 (§9). 게임이 끝나는지는 엔진의 종료 조건이 정한다"""
        return await self._act(
            game_id, user_id, events.ACTION_ELIMINATED,
            lambda s, seat: s.eliminate(seat, "surrender"), reason="surrender",
        )

    async def eliminate(self, game_id: str, seat_no: int, reason: str) -> ActionOutcome:
        """서버 사유 탈락 — 6단계 스위퍼가 time_forfeit / disconnect_forfeit 로 부른다"""
        return await self._act(
            game_id, None, events.ACTION_ELIMINATED,
            lambda s, _: s.eliminate(seat_no, reason), reason=reason, seat_no=seat_no,
        )

    async def void_lost_game(self, game_id: str) -> None:
        """Redis 상태를 잃은 게임을 무효로 닫는다 (§8 fail-safe — 감지는 6단계)

        DB 는 전원 void, MMR 변동 없음. 남은 meta·activity 를 정리한다.
        """
        await self._void_record(game_id)
        redis = require_redis()
        async with store_errors():
            raw_meta = await redis.get(keys.game_meta(game_id))
        if raw_meta is not None:
            meta = GameMeta.from_json(raw_meta)
            await self._publisher.publish(events.game_voided(meta))
            for user_id in meta.human_user_ids:
                await activity.release(redis, user_id, keys.activity_game(game_id))
            async with store_errors():
                await redis.delete(keys.game_meta(game_id), keys.game_state(game_id))

    # ----- 내부 -----

    async def _act(
        self,
        game_id: str,
        user_id: Optional[int],
        action: str,
        apply,
        *,
        reason: Optional[str] = None,
        seat_no: Optional[int] = None,
    ) -> ActionOutcome:
        """락 → 읽기 → 판정 → 펜싱 저장 → (종료 시) 기록 → 발행

        user_id=None 은 서버 행위이고 그때는 seat_no 로 대상 좌석을 받는다.
        action·reason 은 발행할 last_action 에만 쓴다 (좌표는 싣지 않는다).
        """
        redis = require_redis()
        lock_key = keys.game_lock(game_id)
        try:
            async with redis_lock(redis, lock_key) as token:
                async with store_errors():
                    raw_state, raw_meta = await redis.mget(
                        keys.game_state(game_id), keys.game_meta(game_id)
                    )
                if raw_state is None or raw_meta is None:
                    raise GameNotFound(game_id)
                state = _decode_state(raw_state)
                meta = GameMeta.from_json(raw_meta)

                if user_id is not None:
                    seat_no = meta.seat_of(user_id)
                    if seat_no is None or state.seat(seat_no).is_eliminated:
                        return ActionOutcome("not_in_game", state, ended=False)

                was_finished = state.is_finished
                rejection = apply(state, seat_no)
                ended = state.is_finished and not was_finished

                # 거절도 저장한다 — 벽 거절은 wall_rejections 를 바꾼다 (§7)
                ttl = settings.game_finished_ttl_sec if state.is_finished else None
                written = await fenced_set(
                    redis, lock_key, token, keys.game_state(game_id),
                    json.dumps(state.to_dict()), ex=ttl,
                )
                if not written:
                    raise GameBusy(f"lost lock on {game_id} before write")

                if ended:
                    await self._finalize(redis, state, meta)
                if rejection is None:
                    # 락 안에서 발행한다 — 같은 게임의 이벤트가 상태 순서대로 나간다
                    await self._publisher.publish(events.game_updated(
                        meta, state, seat_no=seat_no, action=action, reason=reason, ended=ended,
                    ))
                return ActionOutcome(rejection.value if rejection else None, state, ended)
        except LockTimeout as exc:
            raise GameBusy(str(exc)) from exc

    async def _finalize(self, redis, state: GameState, meta: GameMeta) -> None:
        """종료 처리 — meta 보존 기한 설정, activity 해제, DB 결과 기록

        DB 기록이 실패해도 게임 종료는 확정이다(로그만 남긴다). 재시도는 범위 밖.
        """
        async with store_errors():
            await redis.expire(keys.game_meta(state.game_id), settings.game_finished_ttl_sec)
        for user_id in meta.human_user_ids:
            await activity.release(redis, user_id, keys.activity_game(state.game_id))

        factory = self._session_factory()
        if factory is None:
            return
        try:
            async with factory() as session:
                await GameSessionRepository(session).record_result(
                    state.game_id,
                    end_reason=state.end_reason.value,
                    winner_seat_no=state.winner_seat_no,
                    turn_count=state.turn_count,
                    results=seat_results(state),
                )
        except Exception:
            logger.exception("Failed to record result of game %s", state.game_id)

    async def _void_record(self, game_id: str) -> None:
        factory = self._session_factory()
        if factory is None:
            return
        try:
            async with factory() as session:
                await GameSessionRepository(session).void(game_id)
        except Exception:
            logger.exception("Failed to void game %s", game_id)


maze_games = MazeGameService()

__all__ = [
    "GAME",
    "ActionOutcome",
    "GameBusy",
    "GameMeta",
    "GameNotFound",
    "MazeGameService",
    "MultiplayerError",
    "SeatPlayer",
    "StateVersionMismatch",
    "maze_games",
    "seat_results",
]
