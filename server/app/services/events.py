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
SEAT_DISCONNECTED = "seat_disconnected"
SEAT_RECONNECTED = "seat_reconnected"
MATCHED = "matched"
MATCH_READY = "match_ready"
MATCH_EXPIRED = "match_expired"
ROOM_UPDATED = "room_updated"
ROOM_DISSOLVED = "room_dissolved"
SESSION_REPLACED = "session_replaced"   # user 범위 — 같은 계정의 새 연결 (M3 7단계)

# room_updated hint 의 change.kind — 수신자별 §12 메시지(player_joined·player_ready·player_left)를 고른다
ROOM_CREATED = "created"
ROOM_JOINED = "joined"
ROOM_LEFT = "left"
ROOM_READY = "ready"
ROOM_SETTINGS = "settings"

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
    seq: int = 0                  # game: 게임별 단조 번호(game:{id}:version) — 서비스가 커밋 때 매긴다(검토 L23)

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
    """앱 Redis 로 PUBLISH. 실패는 로그만 남긴다

    in_commit: 게임 서비스가 상태 쓰기(펜싱 Lua)와 **같은 스크립트에서** 발행해도 되는 발행자다 — 쓰기 직후·발행 전에
    워커가 죽어 통지가 사라지는 창을 없앤다(M4-1 독립 검토, S4 kill 간헐 실패). 테스트의 기록용 발행자는 이 속성이 없어
    지금처럼 쓰기 뒤에 받는다.
    """

    in_commit = True

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
    # 생존자 수는 공개 정보이고 "통보 시점" 값이다(§9) — 늦게 전달돼도 다시 읽은 상태로 세지 않게 싣는다
    if action == ACTION_ELIMINATED:
        last_action["survivors"] = len(state.survivors)
    return Event(
        kind=GAME_UPDATED,
        scope="game",
        scope_id=meta.game_id,
        recipients=_unique(meta.human_user_ids),
        hint={"last_action": last_action, "ended": ended},
    )


def game_voided(game_id: str, recipients: Iterable[Optional[int]]) -> Event:
    """무효 처리 통지. 수신자는 meta 가 있으면 meta 에서, Redis 를 통째로 잃었으면 DB 참가자에서 온다"""
    return Event(
        kind=GAME_VOIDED,
        scope="game",
        scope_id=game_id,
        recipients=_unique(recipients),
    )


def seat_disconnected(meta: "GameMeta", seat_no: int, grace_remaining_ms: int, survivors: int) -> Event:
    """접속 시계가 흐르기 시작했다 (§9 `player_left state=reconnecting`). 남은 접속 시계는 공개 정보다(§8)"""
    return Event(
        kind=SEAT_DISCONNECTED,
        scope="game",
        scope_id=meta.game_id,
        recipients=_unique(meta.human_user_ids),
        hint={"seat_no": seat_no, "grace_remaining_ms": grace_remaining_ms, "survivors": survivors},
    )


def seat_reconnected(meta: "GameMeta", seat_no: int) -> Event:
    return Event(
        kind=SEAT_RECONNECTED,
        scope="game",
        scope_id=meta.game_id,
        recipients=_unique(meta.human_user_ids),
        hint={"seat_no": seat_no},
    )


# ----- 매치 -----

def _match_players(match: "PendingMatch") -> list[dict]:
    return [
        {"seat_no": p.seat_no, "user_id": p.user_id, "nickname": p.nickname, "mmr": p.mmr, "ready": p.ready}
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
        hint={"game": match.game, "mode": match.mode,
              "requeued": list(result.requeued), "dropped": list(result.dropped)},
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


def room_updated(room: "Room", change: str, actor_user_id: int, seat_no: Optional[int] = None,
                 *, also_notify: Iterable[int] = ()) -> Event:
    """change: 무엇이 바뀌었나(ROOM_*), actor: 바꾼 사람 — 그 사람은 핸들러 응답으로 받으므로 버스가 건너뛴다.
    seat_no 는 바뀐 좌석(나간 사람은 나가기 전 좌석). also_notify: 방에서 막 나간 사람처럼 room.players 에 없지만
    알아야 하는 유저"""
    return Event(
        kind=ROOM_UPDATED,
        scope="room",
        scope_id=room.code,
        recipients=_unique([*room.user_ids, *also_notify]),
        hint={
            "room": room_snapshot(room),
            "change": {"kind": change, "seat_no": seat_no, "actor_user_id": actor_user_id},
        },
    )


def room_dissolved(result: "LeaveResult") -> Event:
    return Event(
        kind=ROOM_DISSOLVED,
        scope="room",
        scope_id=result.room.code,
        recipients=_unique(result.notify_user_ids),
        hint={"code": result.room.code},
    )


# ----- 유저 -----

def session_replaced(user_id: int, conn_id: str) -> Event:
    """같은 계정의 새 연결 — conn_id 가 아닌 그 유저의 로컬 연결은 4000 으로 닫는다(판단 4)

    conn_id 는 워커 id 를 담는다. 채널은 서버 안쪽(워커들)만 구독하고 클라이언트에는 나가지 않는다.
    """
    return Event(
        kind=SESSION_REPLACED,
        scope="user",
        scope_id=str(user_id),
        recipients=(user_id,),
        hint={"conn_id": conn_id},
    )
