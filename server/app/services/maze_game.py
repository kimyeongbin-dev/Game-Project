"""
1인칭 미로 게임 서비스 — 진행 중 상태(Redis 권위) + 종료 기록(PostgreSQL).

docs/api/games/maze.md §8: 게임 상태의 권위는 Redis `game:<id>:state` 다. 워커는 상태를
소유하지 않는다. 어느 워커든 행동을 받으면 게임별 락을 잡고 상태를 읽어 판정하고,
락 토큰으로 펜싱해 기록한다. 그래서 워커가 죽거나 교체되어도 게임이 이어진다.

- 엔진(`app.games.maze`)은 저장소·유저를 모른다. 유저 ↔ 좌석 매핑은 `game:<id>:meta` 몫이다
- 시작 시 DB 에 진행 중 행을 먼저 쓴다. §8 fail-safe 는 "DB 에는 진행 중인데 Redis 상태가
  없다"를 유실 판정 기준으로 쓴다
- 좌석별 누적 시야(`game:<id>:vision:<seat_no>`, maze.md §6)는 수락된 행동마다 생존 좌석 전원을
  다시 관측해 state 와 **같은 펜싱 쓰기 한 번**으로 기록한다. 탈락 좌석은 탈락 직전 관측으로 동결된다
- 상태를 쓴 직후(락 안에서) 이벤트를 발행만 한다(`app/services/events.py`). 소켓 전송은 ws 계층
  구독 버스가 한다. 거절은 발행하지 않는다 — 행동한 사람에게만 응답한다(핸들러, 7단계)
- 시간 체계(maze.md §8·§9, M3 6단계): 좌석별 게임 시계·접속 시계(`game:<id>:clocks`, 계산은
  `maze_clock.py`)와 데드라인 색인(`deadlines:<game>`)을 state 와 **같은 펜싱 쓰기 한 번**으로 기록한다.
  시각은 Redis TIME(주입 가능). 모든 처리는 맨 앞에서 소진된 시계를 먼저 탈락 처리한다(지연 보정)
"""

import json
import logging
import random
from dataclasses import asdict, dataclass, field
from typing import Callable, Optional, Sequence

from sqlalchemy.ext.asyncio import async_sessionmaker

from app.core.config import settings
from app.core.time import Clock, redis_clock, utcnow
from app.db import redis_keys as keys
from app.db.config import get_session_factory, is_db_available
from app.db.redis_lock import (
    LockTimeout,
    fenced_write,
    redis_lock,
    require_redis,
    store_errors,
)
from app.db.repository import GameSessionRepository, ParticipantSeed, SeatResult
from app.games.maze import GameState
from app.games.maze.core.game_state import SCHEMA_VERSION
from app.games.maze.core.layouts import get_layout
from app.games.maze.core.vision import SeatMemory, game_sight
from app.services import activity, events, outages
from app.services.activity import MultiplayerError
from app.services.events import Publisher, redis_publisher
from app.services.maze_clock import GameClocks, Interval

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
    # 친구 방 설정 — 탈락자가 관전 패킷(전체 판 + 생존자 시야)을 받는다. 랭크는 항상 False
    spectate_on_elimination: bool = False

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


def _decode_memory(raw: Optional[str]) -> SeatMemory:
    """저장된 좌석 관측. 없으면 빈 기억, 버전이 다르면 StateVersionMismatch"""
    if raw is None:
        return SeatMemory()
    try:
        return SeatMemory.from_dict(json.loads(raw))
    except ValueError as exc:
        raise StateVersionMismatch(str(exc)) from exc


def _encode_memory(memory: SeatMemory) -> str:
    return json.dumps(memory.to_dict())


def _observe(state: GameState, seat_no: int, memory: SeatMemory) -> SeatMemory:
    """생존 좌석은 지금 시야를 더한다. 탈락 좌석은 눈을 감는다 — 그대로 둔다(계획서 판단 3)"""
    if state.seat(seat_no).is_eliminated:
        return memory
    return memory.observe(game_sight(state, seat_no), state.turn_count)


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


@dataclass(frozen=True)
class Disconnection:
    """mark_disconnected 결과 — 서버 유예 소급(apply_server_grace)이 이 시각으로 같은 끊김인지 확인한다"""
    seat_no: int
    disconnected_at_ms: int
    grace_remaining_ms: int


@dataclass(frozen=True)
class GraceEntry:
    """서버 유예 후보 — 이 워커가 기록한 끊김 하나 (app/ws/server_grace.py)"""
    game_id: str
    user_id: int
    disconnected_at_ms: int


@dataclass
class _Tx:
    """게임 락 안의 처리 한 번 — 읽은 것, 바꾼 것, 나갈 이벤트"""
    state: GameState
    meta: GameMeta
    clocks: GameClocks
    now: int
    outages: list[Interval]
    outbox: list[events.Event] = field(default_factory=list)
    expired: list[tuple[int, str]] = field(default_factory=list)
    observe: bool = False

    @property
    def current(self) -> Optional[int]:
        return None if self.state.is_finished else self.state.current_seat_no


def _decode_clocks(raw: Optional[str]) -> GameClocks:
    if raw is None:
        raise StateVersionMismatch("clocks missing")
    try:
        return GameClocks.from_dict(json.loads(raw))
    except ValueError as exc:
        raise StateVersionMismatch(str(exc)) from exc


def deadline_ops(state: GameState, clocks: GameClocks,
                 outage_list: Sequence[Interval] = ()) -> tuple[dict[str, int], list[str]]:
    """이 게임의 데드라인 member → (ZADD 할 것, ZREM 할 것). 좌석 목록에서 만든다 — 인원 수 무관"""
    gid = state.game_id
    due = clocks.deadlines(None if state.is_finished else state.current_seat_no, outage_list)
    zadd: dict[str, int] = {}
    zrem: list[str] = []
    if due.clock_at is not None:
        zadd[keys.deadline_clock(gid)] = due.clock_at
    else:
        zrem.append(keys.deadline_clock(gid))
    for p in state.seats:
        member = keys.deadline_grace(gid, p.seat_no)
        if p.seat_no in due.grace_at:
            zadd[member] = due.grace_at[p.seat_no]
        else:
            zrem.append(member)
    return zadd, zrem


class MazeGameService:
    """상태는 Redis·DB 에만 있다. 인스턴스는 의존성(DB 세션 팩토리·발행·시계)만 들고 있다"""

    def __init__(
        self,
        session_factory: SessionFactoryProvider = _app_session_factory,
        publisher: Publisher = redis_publisher,
        clock: Clock = redis_clock,
    ):
        self._session_factory = session_factory
        self._publisher = publisher
        self._clock = clock

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
        spectate_on_elimination: bool = False,
    ) -> GameState:
        """게임 시작. 좌석은 배치 테이블 정원 1..N 을 정확히 채워야 한다

        spectate_on_elimination 은 친구 방 설정이다. 랭크 게임에서는 켤 수 없다.

        사람 좌석의 activity 를 game:<id> 로 덮어쓴다. 호출자(매치·방)가 그 유저들의
        이전 활동을 쥐고 있는 상태에서 부른다.
        """
        seats = self.seats(mode)
        if sorted(p.seat_no for p in players) != list(range(1, seats + 1)):
            raise ValueError(f"mode {mode} needs seats 1..{seats}, got {[p.seat_no for p in players]}")
        if is_ranked and spectate_on_elimination:
            raise ValueError("ranked games never allow spectating on elimination")

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
            spectate_on_elimination=spectate_on_elimination,
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
            now = await self._clock.now_ms()
            clocks = GameClocks.start(
                [p.seat_no for p in state.seats], now,
                initial_ms=settings.clock_initial_ms, budget_ms=settings.connection_budget_ms,
            )
            zadd, _ = deadline_ops(state, clocks)
            async with store_errors():
                async with redis.pipeline(transaction=True) as pipe:
                    pipe.set(keys.game_state(state.game_id), json.dumps(state.to_dict()))
                    pipe.set(keys.game_meta(state.game_id), meta.to_json())
                    pipe.set(keys.game_clocks(state.game_id), json.dumps(clocks.to_dict()))
                    for p in state.seats:  # 초기 관측 (turn 0)
                        pipe.set(keys.game_vision(state.game_id, p.seat_no),
                                 _encode_memory(_observe(state, p.seat_no, SeatMemory())))
                    for user_id in meta.human_user_ids:
                        pipe.set(keys.user_activity(user_id), keys.activity_game(state.game_id))
                    pipe.zadd(keys.deadlines(GAME), zadd)
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

    async def load_with_vision(
        self, game_id: str, seat_nos: Sequence[int]
    ) -> tuple[Optional[GameState], dict[int, SeatMemory], Optional[GameClocks]]:
        """state·시계와 지정한 좌석들의 누적 관측을 MGET 한 번으로 — 찢어진 읽기가 없는 스냅샷"""
        redis = require_redis()
        async with store_errors():
            raw_state, raw_clocks, *raw_vision = await redis.mget(
                keys.game_state(game_id), keys.game_clocks(game_id),
                *(keys.game_vision(game_id, s) for s in seat_nos),
            )
        if raw_state is None:
            return None, {}, None
        clocks = _decode_clocks(raw_clocks) if raw_clocks is not None else None
        return _decode_state(raw_state), {
            s: _decode_memory(raw) for s, raw in zip(seat_nos, raw_vision)
        }, clocks

    async def public_clocks(self, state: GameState, clocks: Optional[GameClocks]) -> Optional[dict]:
        """전원에게 공개하는 시계 잔량 — 지금 시각(Redis TIME) 기준 지연 정산 값 (§8)"""
        if clocks is None:
            return None
        now = await self._clock.now_ms()
        outage_list = await outages.read(require_redis(), clocks.open_since())
        return clocks.public_view(None if state.is_finished else state.current_seat_no, now, outage_list)

    async def load_clocks(self, game_id: str) -> Optional[GameClocks]:
        """시계 스냅샷 (락 없음). 없으면 None"""
        redis = require_redis()
        async with store_errors():
            raw = await redis.get(keys.game_clocks(game_id))
        return _decode_clocks(raw) if raw is not None else None

    async def get_meta(self, game_id: str) -> Optional[GameMeta]:
        redis = require_redis()
        async with store_errors():
            raw = await redis.get(keys.game_meta(game_id))
        return GameMeta.from_json(raw) if raw is not None else None

    # ----- 행동 (클라이언트 — 좌석·시각을 받지 않는다) -----

    async def move(self, game_id: str, user_id: int, row: int, col: int) -> ActionOutcome:
        return await self._player_action(
            game_id, user_id, events.ACTION_MOVE, lambda s, seat: s.move(seat, row, col)
        )

    async def place_wall(
        self, game_id: str, user_id: int, row: int, col: int, orientation: str
    ) -> ActionOutcome:
        return await self._player_action(
            game_id, user_id, events.ACTION_WALL,
            lambda s, seat: s.place_wall(seat, row, col, orientation),
        )

    async def surrender(self, game_id: str, user_id: int) -> ActionOutcome:
        """즉시 탈락 (§9). 게임이 끝나는지는 엔진의 종료 조건이 정한다"""
        return await self._player_action(game_id, user_id, events.ACTION_ELIMINATED, None)

    # ----- 연결 (7단계 핸들러가 부른다 — user_id 는 인증된 연결에서만) -----

    async def mark_disconnected(self, game_id: str, user_id: int) -> Optional[Disconnection]:
        """끊김 — 그 좌석의 접속 시계가 흐르기 시작한다 (§8·§9)

        이미 끊김이면 처음 끊긴 시각을 그대로 둔다. 좌석이 아니거나 탈락·종료면 None.
        """
        def step(tx: _Tx) -> Optional[Disconnection]:
            seat_no = tx.meta.seat_of(user_id)
            if seat_no is None or tx.state.is_finished or tx.state.seat(seat_no).is_eliminated:
                return None
            fresh = tx.clocks.disconnect(seat_no, tx.now)
            seat = tx.clocks.seat(seat_no)
            remaining = max(0, tx.clocks.conn_remaining(seat_no, tx.now, tx.outages))
            if fresh:
                tx.outbox.append(events.seat_disconnected(tx.meta, seat_no, remaining, tx.state.turn_count))
            return Disconnection(seat_no, seat.disconnected_at_ms, remaining)

        result, _, _ = await self._run(game_id, step)
        return result

    async def mark_connected(self, game_id: str, user_id: int) -> bool:
        """재접속 — 끊긴 구간을 접속 시계에서 차감한다(리셋 없음). 끊김 상태였으면 True"""
        def step(tx: _Tx) -> bool:
            seat_no = tx.meta.seat_of(user_id)
            if seat_no is None or tx.state.seat(seat_no).is_eliminated:
                return False
            return self._reconnect(tx, seat_no)

        result, _, _ = await self._run(game_id, step)
        return result

    async def apply_server_grace(self, entries: Sequence[GraceEntry]) -> int:
        """배포로 끊긴 좌석에 서버 유예를 소급한다 (§8). 적용한 좌석 수

        lifespan shutdown 전용(app/ws/server_grace.py). 좌석이 **아직 같은 끊김**일 때만 —
        그 사이 재접속했거나 다시 끊겼으면 건드리지 않는다. 데드라인은 같은 쓰기로 다시 적힌다.
        """
        applied = 0
        for entry in entries:
            def step(tx: _Tx, entry=entry) -> bool:
                seat_no = tx.meta.seat_of(entry.user_id)
                if seat_no is None:
                    return False
                return tx.clocks.apply_grace(seat_no, entry.disconnected_at_ms, settings.server_grace_max_ms)

            try:
                ok, _, _ = await self._run(entry.game_id, step)
            except GameNotFound:
                continue
            applied += int(ok)
        return applied

    # ----- 서버 행위 (스위퍼·운영 — 소켓 메시지에 연결하지 않는다) -----

    async def eliminate(self, game_id: str, seat_no: int, reason: str) -> ActionOutcome:
        """서버 사유 탈락. 이미 탈락한 좌석이면 not_in_game"""
        def step(tx: _Tx):
            if tx.state.seat(seat_no).is_eliminated:
                return "not_in_game"
            rejection = self._eliminate(tx, seat_no, reason)
            return rejection.value if rejection else None

        rejection, tx, ended = await self._run(game_id, step)
        return ActionOutcome(rejection, tx.state, ended)

    async def expire(self, game_id: str) -> list[tuple[int, str]]:
        """만료 정산만 — 스위퍼가 부른다. 이번에 탈락시킨 (좌석, 사유) 목록

        정산은 락 안에서 저장된 시계로 다시 계산한다. 데드라인 점수가 낡았어도 결과가 틀리지 않고,
        올바른 점수로 다시 적힌다. 같은 만료를 두 번 불러도 두 번째는 빈 목록이다.
        """
        _, tx, _ = await self._run(game_id, lambda tx: None)
        return tx.expired

    async def void_lost_game(self, game_id: str) -> bool:
        """Redis 상태를 잃은 게임을 무효로 닫는다 (§8 fail-safe). 실제로 닫았으면 True

        state 가 아직 있으면 아무것도 하지 않는다. 여러 번·여러 워커가 불러도 통지는 한 번이다.
        """
        return await self._void(game_id, lost=True)

    async def void_game(self, game_id: str, *, started_before_ms: Optional[int] = None) -> bool:
        """진행 중인 게임을 무효로 닫는다 — 긴 Redis 장애 (§8). 실제로 닫았으면 True

        started_before_ms 가 있으면 그 전에 시작한 게임만 (장애 뒤에 생긴 게임은 건드리지 않는다).
        """
        return await self._void(game_id, lost=False, started_before_ms=started_before_ms)

    # ----- 내부 -----

    async def _player_action(self, game_id: str, user_id: int, action: str, apply) -> ActionOutcome:
        def step(tx: _Tx):
            seat_no = tx.meta.seat_of(user_id)
            # 정산으로 방금 탈락했을 수도 있다 (§8 지연 보정 — 만료를 먼저 처리한다)
            if seat_no is None or tx.state.seat(seat_no).is_eliminated:
                return "not_in_game"
            self._reconnect(tx, seat_no)  # 행동을 보냈다는 것이 연결의 증거다
            if apply is None:
                rejection = self._eliminate(tx, seat_no, "surrender")
                return rejection.value if rejection else None

            rejection = apply(tx.state, seat_no)
            if rejection is not None:
                return rejection.value  # 거절은 시계를 건드리지 않는다 — 차례는 계속 흐른다
            tx.clocks.close_turn(seat_no, tx.now, tx.outages, increment_ms=settings.clock_increment_ms)
            if tx.state.is_finished:
                tx.clocks.stop(tx.now, tx.outages)
            tx.observe = True
            tx.outbox.append(events.game_updated(
                tx.meta, tx.state, seat_no=seat_no, action=action, ended=tx.state.is_finished,
            ))
            return None

        rejection, tx, ended = await self._run(game_id, step)
        return ActionOutcome(rejection, tx.state, ended)

    async def _run(self, game_id: str, step):
        """락 → 읽기(state·meta·clocks) → 시각 → 만료 정산 → step → 펜싱 쓰기 한 번 → (종료 시) 기록 → 발행

        모든 경로(행동·항복·스위퍼·끊김·재접속)가 여기를 지난다. 그래서 만료는 언제나 다른 무엇보다
        먼저 처리되고, 시계·시야·데드라인이 state 와 같은 토큰으로 한 번에 기록된다.
        반환: (step 결과, 처리 맥락, 이번에 종료됐는지)
        """
        redis = require_redis()
        lock_key = keys.game_lock(game_id)
        try:
            async with redis_lock(redis, lock_key) as token:
                async with store_errors():
                    raw_state, raw_meta, raw_clocks = await redis.mget(
                        keys.game_state(game_id), keys.game_meta(game_id), keys.game_clocks(game_id)
                    )
                if raw_state is None or raw_meta is None:
                    raise GameNotFound(game_id)
                state = _decode_state(raw_state)
                clocks = _decode_clocks(raw_clocks)
                tx = _Tx(
                    state=state,
                    meta=GameMeta.from_json(raw_meta),
                    clocks=clocks,
                    now=await self._clock.now_ms(),
                    outages=await outages.read(redis, clocks.open_since()),
                )
                was_finished = state.is_finished
                self._settle(tx)
                result = step(tx)
                ended = state.is_finished and not was_finished

                await self._commit(redis, lock_key, token, tx)
                if ended:
                    await self._finalize(redis, state, tx.meta)
                # 락 안에서 발행한다 — 같은 게임의 이벤트가 상태 순서대로 나간다
                for event in tx.outbox:
                    await self._publisher.publish(event)
                return result, tx, ended
        except LockTimeout as exc:
            raise GameBusy(str(exc)) from exc

    def _settle(self, tx: _Tx) -> None:
        """지금 소진된 시계를 소진 시각 순으로 탈락 처리한다 (탈락 순번 = 순위 근거)"""
        for expiry in tx.clocks.settle(tx.current, tx.now, tx.outages):
            if tx.state.is_finished:
                break
            if tx.state.seat(expiry.seat_no).is_eliminated:
                continue
            self._eliminate(tx, expiry.seat_no, expiry.reason)
            tx.expired.append((expiry.seat_no, expiry.reason))

    def _eliminate(self, tx: _Tx, seat_no: int, reason: str):
        """좌석 탈락 + 시계 (§9 탈락 처리 3·5번). 현재 차례였으면 다음 생존자는 지금부터"""
        was_current = tx.current == seat_no
        rejection = tx.state.eliminate(seat_no, reason)
        if rejection is not None:
            return rejection
        if was_current:
            tx.clocks.close_turn(seat_no, tx.now, tx.outages)  # 증분 없음
        tx.clocks.freeze(seat_no, tx.now, tx.outages)
        if tx.state.is_finished:
            tx.clocks.stop(tx.now, tx.outages)
        elif was_current:
            tx.clocks.begin_turn(tx.now)
        tx.observe = True
        tx.outbox.append(events.game_updated(
            tx.meta, tx.state, seat_no=seat_no, action=events.ACTION_ELIMINATED,
            reason=reason, ended=tx.state.is_finished,
        ))
        return None

    def _reconnect(self, tx: _Tx, seat_no: int) -> bool:
        if not tx.clocks.reconnect(seat_no, tx.current, tx.now, tx.outages):
            return False
        tx.outbox.append(events.seat_reconnected(tx.meta, seat_no, tx.state.turn_count))
        return True

    async def _commit(self, redis, lock_key: str, token: str, tx: _Tx) -> None:
        """state·clocks(·vision)·데드라인을 같은 토큰으로 한 번에 — 전부 또는 전무"""
        gid = tx.state.game_id
        items = {
            keys.game_state(gid): json.dumps(tx.state.to_dict()),
            keys.game_clocks(gid): json.dumps(tx.clocks.to_dict()),
        }
        if tx.observe:
            # 남의 행동도 내 시야를 바꾼다 — 좌석 전원을 state 와 한 번에 쓴다.
            # 동결된 좌석도 다시 써서 종료 TTL 을 같이 받는다
            items.update(await self._observe_all(redis, tx.state))
        zadd, zrem = deadline_ops(tx.state, tx.clocks, tx.outages)
        ttl = settings.game_finished_ttl_sec if tx.state.is_finished else None
        written = await fenced_write(
            redis, lock_key, token, items, ex=ttl,
            zset=keys.deadlines(GAME), zadd=zadd, zrem=zrem,
        )
        if not written:
            raise GameBusy(f"lost lock on {gid} before write")

    async def _observe_all(self, redis, state: GameState) -> dict[str, str]:
        """좌석 전원의 vision 키 → 갱신된 관측 JSON (락 안에서 부른다)"""
        vision_keys = [keys.game_vision(state.game_id, p.seat_no) for p in state.seats]
        async with store_errors():
            raws = await redis.mget(*vision_keys)
        return {
            key: _encode_memory(_observe(state, p.seat_no, _decode_memory(raw)))
            for key, p, raw in zip(vision_keys, state.seats, raws)
        }

    async def _void(self, game_id: str, *, lost: bool, started_before_ms: Optional[int] = None) -> bool:
        """무효 처리 공통 — 락 안에서 조건을 다시 확인하고, 키를 실제로 지운 쪽만 통지한다"""
        redis = require_redis()
        try:
            async with redis_lock(redis, keys.game_lock(game_id)):
                async with store_errors():
                    raw_state, raw_meta, raw_clocks = await redis.mget(
                        keys.game_state(game_id), keys.game_meta(game_id), keys.game_clocks(game_id)
                    )
                if lost and raw_state is not None:
                    return False
                if not lost:
                    if raw_state is None or _decode_state(raw_state).is_finished:
                        return False
                    if (started_before_ms is not None and raw_clocks is not None
                            and _decode_clocks(raw_clocks).started_at_ms >= started_before_ms):
                        return False
                meta = GameMeta.from_json(raw_meta) if raw_meta is not None else None
                seat_nos = [p.seat_no for p in meta.players] if meta is not None else []
                async with store_errors():
                    async with redis.pipeline(transaction=True) as pipe:
                        pipe.delete(
                            keys.game_state(game_id), keys.game_meta(game_id), keys.game_clocks(game_id),
                            *(keys.game_vision(game_id, s) for s in seat_nos),
                        )
                        pipe.zrem(keys.deadlines(GAME), keys.deadline_clock(game_id),
                                  *(keys.deadline_grace(game_id, s) for s in seat_nos))
                        deleted, _ = await pipe.execute()
        except LockTimeout as exc:
            raise GameBusy(str(exc)) from exc

        claimed = deleted > 0
        recorded = await self._void_record(game_id)
        if meta is not None and claimed:
            await self._publisher.publish(events.game_voided(meta))
            for user_id in meta.human_user_ids:
                await activity.release(redis, user_id, keys.activity_game(game_id))
        return claimed or recorded

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

    async def _void_record(self, game_id: str) -> bool:
        """DB 행을 void 로. 실제로 바꿨으면 True (이미 종료·없음·DB 없음이면 False)"""
        factory = self._session_factory()
        if factory is None:
            return False
        try:
            async with factory() as session:
                return await GameSessionRepository(session).void(game_id) is not None
        except ValueError:
            return False  # 이미 종료된 행 — 다른 워커가 먼저 닫았다
        except Exception:
            logger.exception("Failed to void game %s", game_id)
            return False


maze_games = MazeGameService()

__all__ = [
    "GAME",
    "ActionOutcome",
    "Disconnection",
    "GraceEntry",
    "GameBusy",
    "GameMeta",
    "GameNotFound",
    "MazeGameService",
    "MultiplayerError",
    "SeatPlayer",
    "StateVersionMismatch",
    "deadline_ops",
    "maze_games",
    "seat_results",
]
