"""
멀티플레이 이벤트 — 서비스 결과를 워커 간에 알린다 (M3 4단계).

서비스(게임·매치메이킹·방)는 상태를 Redis 에 쓴 직후 이 모듈로 이벤트를 발행한다.
각 워커의 구독 버스(`app/ws/bus.py`)가 받아서 자기 프로세스의 소켓에만 전달한다.

- **권위를 싣지 않는다.** Pub/Sub 은 at-most-once 다(실측 E5). 이벤트는 "무언가 바뀌었다"는
  통지이고, 게임 상태는 수신 측이 Redis 에서 다시 읽어 좌석별로 만든다(maze.md §6·§8)
- **수신자는 발행자가 정한다.** 발행자는 방금 락 안에서 Redis 를 읽었다. 수신 워커가 다시
  읽으면 그 사이 바뀔 수 있고(해산된 방은 키가 없다) 워커 수만큼 GET 이 는다
- **hint 는 공개 정보만.** 채널은 모든 워커에 간다. 좌표·벽·게임 상태를 넣지 않는다(§6 MUST NOT)
- **발행 실패가 행동을 실패시키지 않는다.** 상태는 이미 기록됐고, 재동기화가 복구한다

빌더는 서비스 결과 객체를 덕 타이핑으로 받는다 — 서비스 모듈이 이 모듈을 import 하므로
여기서 서비스 타입을 import 하면 순환한다.
"""

import json
import logging
from dataclasses import asdict, dataclass, field
from typing import TYPE_CHECKING, Iterable, Optional, Protocol

from redis.exceptions import RedisError

from app.db import redis_keys as keys
from app.db.redis import get_redis

if TYPE_CHECKING:  # pragma: no cover
    from app.games.maze import GameState
    from app.services.matchmaking import ExpireResult, PendingMatch
    from app.services.maze_game import GameMeta
    from app.services.rooms import LeaveResult, Room

logger = logging.getLogger(__name__)

# ----- kind -----
GAME_STARTED = "game_started"
GAME_UPDATED = "game_updated"
GAME_VOIDED = "game_voided"
MATCHED = "matched"
MATCH_READY = "match_ready"
MATCH_EXPIRED = "match_expired"
ROOM_UPDATED = "room_updated"
ROOM_DISSOLVED = "room_dissolved"

# last_action.kind — 좌표는 담지 않는다 (§6 "행동 사실은 알리되 위치는 감춘다")
ACTION_MOVE = "move"
ACTION_WALL = "wall"
ACTION_ELIMINATED = "eliminated"


@dataclass(frozen=True)
class Event:
    kind: str
    scope: str                    # keys.EVENT_SCOPES 중 하나
    scope_id: str                 # game_id | match_id | room code
    recipients: tuple[int, ...]   # 사람 user_id
    hint: dict = field(default_factory=dict)
    seq: int = 0                  # game: turn_count — 수신 측이 낡은 이벤트를 알아본다

    @property
    def channel(self) -> str:
        return keys.events(self.scope, self.scope_id)

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False)

    @classmethod
    def from_json(cls, raw: str) -> "Event":
        data = json.loads(raw)
        data["recipients"] = tuple(int(uid) for uid in data["recipients"])
        return cls(**data)


class Publisher(Protocol):
    async def publish(self, event: Event) -> None: ...


class RedisPublisher:
    """앱 Redis 로 PUBLISH. 실패는 로그만 남긴다"""

    async def publish(self, event: Event) -> None:
        client = get_redis()
        if client is None:
            logger.debug("Redis unavailable — event %s dropped", event.kind)
            return
        try:
            await client.publish(event.channel, event.to_json())
        except RedisError as exc:
            logger.warning("Failed to publish %s on %s: %s", event.kind, event.channel, exc)


redis_publisher = RedisPublisher()


def _unique(user_ids: Iterable[Optional[int]]) -> tuple[int, ...]:
    return tuple(dict.fromkeys(uid for uid in user_ids if uid is not None))


# ----- 게임 -----

def game_started(meta: "GameMeta") -> Event:
    return Event(
        kind=GAME_STARTED,
        scope="game",
        scope_id=meta.game_id,
        recipients=_unique(meta.human_user_ids),
        hint={
            "mode": meta.mode,
            "is_ranked": meta.is_ranked,
            "players": [
                {"seat_no": p.seat_no, "user_id": p.user_id, "nickname": p.nickname, "is_ai": p.is_ai}
                for p in meta.players
            ],
        },
    )


def game_updated(
    meta: "GameMeta",
    state: "GameState",
    *,
    seat_no: int,
    action: str,
    reason: Optional[str] = None,
    ended: bool,
) -> Event:
    last_action = {"seat_no": seat_no, "kind": action}
    if reason is not None:
        last_action["reason"] = reason
    return Event(
        kind=GAME_UPDATED,
        scope="game",
        scope_id=meta.game_id,
        recipients=_unique(meta.human_user_ids),
        hint={"last_action": last_action, "ended": ended},
        seq=state.turn_count,
    )


def game_voided(meta: "GameMeta") -> Event:
    return Event(
        kind=GAME_VOIDED,
        scope="game",
        scope_id=meta.game_id,
        recipients=_unique(meta.human_user_ids),
    )


# ----- 매치 -----

def _match_players(match: "PendingMatch") -> list[dict]:
    return [
        {"seat_no": p.seat_no, "user_id": p.user_id, "nickname": p.nickname, "ready": p.ready}
        for p in match.players
    ]


def matched(match: "PendingMatch") -> Event:
    return Event(
        kind=MATCHED,
        scope="match",
        scope_id=match.match_id,
        recipients=_unique(p.user_id for p in match.players),
        hint={
            "game": match.game,
            "mode": match.mode,
            "ready_deadline_ms": match.ready_deadline_ms,
            "players": _match_players(match),
        },
    )


def match_ready(match: "PendingMatch", seat_no: int) -> Event:
    return Event(
        kind=MATCH_READY,
        scope="match",
        scope_id=match.match_id,
        recipients=_unique(p.user_id for p in match.players),
        hint={"seat_no": seat_no, "players": _match_players(match)},
    )


def match_expired(match: "PendingMatch", result: "ExpireResult") -> Event:
    return Event(
        kind=MATCH_EXPIRED,
        scope="match",
        scope_id=match.match_id,
        recipients=_unique([*result.requeued, *result.dropped]),
        hint={"requeued": list(result.requeued), "dropped": list(result.dropped)},
    )


# ----- 방 -----

def room_snapshot(room: "Room") -> dict:
    """방은 비밀이 없다 — 그대로 공개한다"""
    return {
        "code": room.code,
        "game": room.game,
        "mode": room.mode,
        "capacity": room.capacity,
        "status": room.status,
        "allow_spectate": room.allow_spectate,
        "players": [
            {"seat_no": p.seat_no, "user_id": p.user_id, "nickname": p.nickname,
             "is_host": p.is_host, "is_ready": p.is_ready}
            for p in room.players
        ],
    }


def room_updated(room: "Room", *, also_notify: Iterable[int] = ()) -> Event:
    """also_notify: 방에서 막 나간 사람처럼 room.players 에 없지만 알아야 하는 유저"""
    return Event(
        kind=ROOM_UPDATED,
        scope="room",
        scope_id=room.code,
        recipients=_unique([*room.user_ids, *also_notify]),
        hint={"room": room_snapshot(room)},
    )


def room_dissolved(result: "LeaveResult") -> Event:
    return Event(
        kind=ROOM_DISSOLVED,
        scope="room",
        scope_id=result.room.code,
        recipients=_unique(result.notify_user_ids),
        hint={"code": result.room.code},
    )
