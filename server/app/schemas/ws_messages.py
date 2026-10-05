"""
1인칭 미로 WebSocket 메시지 어휘 (docs/api/games/maze.md §12)

어휘는 구 Quoridor 의 `WSMessageType` 25종을 그대로 쓴다(M3 3단계에 삭제한 같은 이름 파일의 어휘, 커밋 `149ff03^`).
**새 타입을 추가하지 않는다** — §12 의 제약이다. 운용되는 것은 24종이고 `turn_timeout` 은 폐기(턴 타이머가 없다, §8).

클라이언트 페이로드 모델은 **타입만** 검사한다. 좌표 범위·방향 값은 엔진이 판정한다 — §7 "범위 밖 좌표는 거절 카운터에
세지 않는다"를 엔진이 지키려면 여기서 먼저 걸러서는 안 된다. 정의되지 않은 필드는 버린다: 페이로드에 `seat_no`·`user_id`·
시각을 실어도 아무 효과가 없다(좌석은 서버가 인증된 유저로 정하고, 시각은 서버가 찍는다).
"""

from enum import Enum

from pydantic import BaseModel, ConfigDict, StrictBool, StrictInt, StrictStr


class WSMessageType(str, Enum):
    # 클라이언트 → 서버 (10종)
    JOIN_QUEUE = "join_queue"
    LEAVE_QUEUE = "leave_queue"
    CREATE_ROOM = "create_room"
    JOIN_ROOM = "join_room"
    LEAVE_ROOM = "leave_room"
    READY = "ready"
    MOVE = "move"
    WALL = "wall"
    SURRENDER = "surrender"
    CHAT = "chat"               # 유보 — feature_disabled 로 거절한다

    # 서버 → 클라이언트 (15종)
    CONNECTED = "connected"
    QUEUE_JOINED = "queue_joined"
    QUEUE_STATUS = "queue_status"
    MATCHED = "matched"
    ROOM_CREATED = "room_created"
    ROOM_JOINED = "room_joined"
    PLAYER_JOINED = "player_joined"
    PLAYER_LEFT = "player_left"
    PLAYER_READY = "player_ready"
    GAME_START = "game_start"
    GAME_STATE = "game_state"
    TURN_CHANGE = "turn_change"
    TURN_TIMEOUT = "turn_timeout"   # 폐기 — 송신하지 않는다 (§12). 어휘 집계를 위해서만 남긴다
    GAME_END = "game_end"
    ERROR = "error"


CLIENT_TYPES = frozenset({
    WSMessageType.JOIN_QUEUE, WSMessageType.LEAVE_QUEUE, WSMessageType.CREATE_ROOM,
    WSMessageType.JOIN_ROOM, WSMessageType.LEAVE_ROOM, WSMessageType.READY,
    WSMessageType.MOVE, WSMessageType.WALL, WSMessageType.SURRENDER, WSMessageType.CHAT,
})
SERVER_TYPES = frozenset(WSMessageType) - CLIENT_TYPES
RETIRED_TYPES = frozenset({WSMessageType.TURN_TIMEOUT})


class _Payload(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)


class EmptyPayload(_Payload):
    """leave_queue · leave_room · ready · surrender · chat — 본문을 읽지 않는다"""


class JoinQueuePayload(_Payload):
    mode: StrictStr


class CreateRoomPayload(_Payload):
    mode: StrictStr
    allow_spectate: StrictBool = False


class JoinRoomPayload(_Payload):
    room_code: StrictStr


class MovePayload(_Payload):
    row: StrictInt
    col: StrictInt


class WallPayload(_Payload):
    row: StrictInt
    col: StrictInt
    orientation: StrictStr


PAYLOAD_MODELS: dict[WSMessageType, type[_Payload]] = {
    WSMessageType.JOIN_QUEUE: JoinQueuePayload,
    WSMessageType.LEAVE_QUEUE: EmptyPayload,
    WSMessageType.CREATE_ROOM: CreateRoomPayload,
    WSMessageType.JOIN_ROOM: JoinRoomPayload,
    WSMessageType.LEAVE_ROOM: EmptyPayload,
    WSMessageType.READY: EmptyPayload,
    WSMessageType.MOVE: MovePayload,
    WSMessageType.WALL: WallPayload,
    WSMessageType.SURRENDER: EmptyPayload,
    WSMessageType.CHAT: EmptyPayload,
}
