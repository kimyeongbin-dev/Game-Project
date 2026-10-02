"""
친구 대전 방 — Redis `room:{code}` 하나에 방 전체를 담고, 변경은 방 락으로 직렬화한다.

docs/api/games/maze.md §4. 게임 무관하다 — 정원은 그 게임 서비스의 `seats(mode)` 가 정한다.

- 방 seat_no = 게임 seat_no (호스트 = 1, 나머지는 입장 순). §4 `room_created` 페이로드의
  seat_no 가 그대로 게임 좌석이 된다 (사용자 결정 — 랭크 매칭만 좌석을 섞는다)
- 게스트가 나가면 뒤 좌석을 당겨 1..N 을 유지한다. 호스트가 나가면 방을 해산한다
- 방 코드는 `SET NX` 로 확보한다 — 충돌 없이 원자적이다. 구 `MAX_ROOMS` 상한은 없앴다.
  누수는 TTL 이 막는다 (방이 바뀔 때마다 갱신)
- 비랭크 경기다. 결과는 game_sessions 에 is_ranked=false 로 남는다
"""

import json
import random
import string
from contextlib import asynccontextmanager
from dataclasses import asdict, dataclass, replace
from typing import AsyncIterator, Callable, Mapping, Optional, Union

from app.core.config import settings
from app.core.time import utcnow
from app.db import redis_keys as keys
from app.db.redis_lock import LockTimeout, redis_lock, require_redis, store_errors
from app.games.maze import GameState
from app.services import activity, events
from app.services.activity import MultiplayerError
from app.services.events import Publisher, redis_publisher
from app.services.matchmaking import GameService
from app.services.maze_game import GAME as MAZE, GameBusy, SeatPlayer, maze_games

ROOM_CODE_LENGTH = 6
ROOM_CODE_CHARS = string.ascii_uppercase + string.digits
_CODE_ATTEMPTS = 100

WAITING = "waiting"
PLAYING = "playing"


@dataclass(frozen=True)
class RoomPlayer:
    seat_no: int
    user_id: int
    nickname: str
    is_host: bool
    is_ready: bool = False


@dataclass(frozen=True)
class Room:
    code: str
    game: str
    mode: str
    capacity: int
    status: str
    game_id: Optional[str]
    created_at: str
    players: tuple[RoomPlayer, ...]
    # 방 설정 — 탈락자가 관전 패킷을 받는다 (maze.md §9). 게임 시작 시 meta 로 복사된다
    allow_spectate: bool = False

    @property
    def user_ids(self) -> list[int]:
        return [p.user_id for p in self.players]

    def to_json(self) -> str:
        return json.dumps(asdict(self))

    @classmethod
    def from_json(cls, raw: str) -> "Room":
        data = json.loads(raw)
        data["players"] = tuple(RoomPlayer(**p) for p in data["players"])
        return cls(**data)


@dataclass(frozen=True)
class LeaveResult:
    room: Room                 # 이탈 반영 후의 방 (해산이면 해산 직전 방)
    dissolved: bool            # 호스트 이탈로 해산됐다
    notify_user_ids: list[int] # 남은 인원 — player_left 를 받을 사람


def _random_code() -> str:
    return "".join(random.choices(ROOM_CODE_CHARS, k=ROOM_CODE_LENGTH))


class Rooms:
    def __init__(
        self,
        games: Optional[Mapping[str, GameService]] = None,
        code_factory: Callable[[], str] = _random_code,
        publisher: Publisher = redis_publisher,
    ):
        self._games = dict(games) if games is not None else {MAZE: maze_games}
        self._code_factory = code_factory
        self._publisher = publisher

    def _service(self, game: str) -> GameService:
        service = self._games.get(game)
        if service is None:
            raise ValueError(f"Unknown game: {game}")
        return service

    # ----- 조회 -----

    async def get_room(self, code: str) -> Optional[Room]:
        redis = require_redis()
        async with store_errors():
            raw = await redis.get(keys.room(code))
        return Room.from_json(raw) if raw is not None else None

    async def _room_code_of(self, redis, user_id: int) -> str:
        current = await activity.current(redis, user_id)
        kind, code = keys.parse_activity(current) if current else ("", "")
        if kind != "room":
            raise MultiplayerError("not_in_room")
        return code

    # ----- 변경 -----

    async def create_room(
        self, game: str, mode: str, user_id: int, nickname: str, *, allow_spectate: bool = False
    ) -> Room:
        capacity = self._service(game).seats(mode)
        redis = require_redis()
        host = RoomPlayer(seat_no=1, user_id=user_id, nickname=nickname, is_host=True)

        for _ in range(_CODE_ATTEMPTS):
            room = Room(
                code=self._code_factory(), game=game, mode=mode, capacity=capacity,
                status=WAITING, game_id=None, created_at=utcnow().isoformat() + "Z",
                players=(host,), allow_spectate=allow_spectate,
            )
            async with store_errors():
                if await redis.set(keys.room(room.code), room.to_json(), nx=True,
                                   ex=settings.room_ttl_sec):
                    break
        else:
            raise RuntimeError("Failed to allocate a unique room code")

        try:
            await activity.claim(redis, user_id, keys.activity_room(room.code),
                                 ttl_sec=settings.room_ttl_sec)
        except Exception:
            async with store_errors():
                await redis.delete(keys.room(room.code))
            raise
        await self._publisher.publish(events.room_updated(room))
        return room

    async def join_room(self, code: str, user_id: int, nickname: str) -> Room:
        """정원 초과·시작된 방은 room_full, 없는 방은 room_not_found"""
        redis = require_redis()
        async with self._locked(redis, code):
            room = await self._load(redis, code)
            if user_id in room.user_ids:
                return room
            if room.status != WAITING or len(room.players) >= room.capacity:
                raise MultiplayerError("room_full")

            await activity.claim(redis, user_id, keys.activity_room(code),
                                 ttl_sec=settings.room_ttl_sec)
            room = replace(room, players=room.players + (
                RoomPlayer(seat_no=len(room.players) + 1, user_id=user_id,
                           nickname=nickname, is_host=False),
            ))
            await self._save(redis, room)
            await self._publisher.publish(events.room_updated(room))
            return room

    async def leave_room(self, user_id: int) -> LeaveResult:
        """시작 전 이탈. 시작 후에는 활동이 game 이므로 not_in_room — 항복으로 처리한다 (§9)"""
        redis = require_redis()
        code = await self._room_code_of(redis, user_id)
        held = keys.activity_room(code)
        async with self._locked(redis, code):
            room = await self._load(redis, code)
            leaver = next((p for p in room.players if p.user_id == user_id), None)
            if leaver is None:
                await activity.release(redis, user_id, held)
                raise MultiplayerError("not_in_room")

            if leaver.is_host:
                async with store_errors():
                    await redis.delete(keys.room(code))
                for uid in room.user_ids:
                    await activity.release(redis, uid, held)
                others = [uid for uid in room.user_ids if uid != user_id]
                result = LeaveResult(room=room, dissolved=True, notify_user_ids=others)
                await self._publisher.publish(events.room_dissolved(result))
                return result

            remaining = [p for p in room.players if p.user_id != user_id]
            room = replace(room, players=tuple(
                replace(p, seat_no=i + 1) for i, p in enumerate(remaining)
            ))
            await self._save(redis, room)
            await activity.release(redis, user_id, held)
            # 떠난 사람도 받는다 — 다른 워커에 붙은 같은 유저의 화면이 방을 닫게 한다
            await self._publisher.publish(events.room_updated(room, also_notify=[user_id]))
            return LeaveResult(room=room, dissolved=False, notify_user_ids=room.user_ids)

    async def set_ready(self, user_id: int, is_ready: bool = True) -> Union[Room, GameState]:
        """준비 표시. 정원이 차고 전원 준비되면 비랭크 게임을 만들고 GameState 를 돌려준다"""
        redis = require_redis()
        code = await self._room_code_of(redis, user_id)
        async with self._locked(redis, code):
            room = await self._load(redis, code)
            if room.status != WAITING or user_id not in room.user_ids:
                raise MultiplayerError("not_in_room")
            room = replace(room, players=tuple(
                replace(p, is_ready=is_ready) if p.user_id == user_id else p for p in room.players
            ))

            full = len(room.players) == room.capacity
            if not (full and all(p.is_ready for p in room.players)):
                await self._save(redis, room)
                await self._publisher.publish(events.room_updated(room))
                return room

            # 게임 시작 통지는 create_game 이 발행한다 (출처는 하나)
            state = await self._service(room.game).create_game(
                mode=room.mode,
                is_ranked=False,
                players=[SeatPlayer(p.seat_no, p.user_id, p.nickname) for p in room.players],
                room_code=room.code,
                spectate_on_elimination=room.allow_spectate,
            )
            room = replace(room, status=PLAYING, game_id=state.game_id)
            await self._save(redis, room, refresh_members=False)  # 활동은 이제 game 이다
            return state

    # ----- 내부 -----

    def _locked(self, redis, code: str):
        return _room_lock(redis, code)

    async def _load(self, redis, code: str) -> Room:
        async with store_errors():
            raw = await redis.get(keys.room(code))
        if raw is None:
            raise MultiplayerError("room_not_found")
        return Room.from_json(raw)

    async def _save(self, redis, room: Room, *, refresh_members: bool = True) -> None:
        """방을 쓰고 TTL 을 갱신한다. 멤버 활동의 TTL 도 방과 맞춘다"""
        async with store_errors():
            async with redis.pipeline(transaction=True) as pipe:
                pipe.set(keys.room(room.code), room.to_json(), ex=settings.room_ttl_sec)
                if refresh_members:
                    for uid in room.user_ids:
                        pipe.expire(keys.user_activity(uid), settings.room_ttl_sec)
                await pipe.execute()


@asynccontextmanager
async def _room_lock(redis, code: str) -> AsyncIterator[None]:
    """방 락. 대기 초과는 GameBusy 로 바꾼다"""
    try:
        async with redis_lock(redis, keys.room_lock(code)):
            yield
    except LockTimeout as exc:
        raise GameBusy(str(exc)) from exc


rooms = Rooms()
