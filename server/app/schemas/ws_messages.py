"""
WebSocket Message Schemas
실시간 게임 통신용 메시지 스키마
"""

from typing import Optional, Literal, Any
from pydantic import BaseModel, Field
from enum import Enum


class WSMessageType(str, Enum):
    """WebSocket 메시지 타입"""
    # 클라이언트 → 서버
    JOIN_QUEUE = "join_queue"           # 랭킹전 매칭 큐 참가
    LEAVE_QUEUE = "leave_queue"         # 매칭 큐 나가기
    CREATE_ROOM = "create_room"         # 친구대전 방 생성
    JOIN_ROOM = "join_room"             # 친구대전 방 참가
    LEAVE_ROOM = "leave_room"           # 방 나가기
    READY = "ready"                     # 준비 완료
    MOVE = "move"                       # 폰 이동
    WALL = "wall"                       # 벽 설치
    SURRENDER = "surrender"             # 항복
    CHAT = "chat"                       # 채팅 (선택)

    # 서버 → 클라이언트
    CONNECTED = "connected"             # 연결 성공
    QUEUE_JOINED = "queue_joined"       # 큐 참가 완료
    QUEUE_STATUS = "queue_status"       # 큐 상태 (대기 인원 등)
    MATCHED = "matched"                 # 매칭 완료
    ROOM_CREATED = "room_created"       # 방 생성 완료
    ROOM_JOINED = "room_joined"         # 방 참가 완료
    PLAYER_JOINED = "player_joined"     # 상대방 입장
    PLAYER_LEFT = "player_left"         # 상대방 퇴장
    PLAYER_READY = "player_ready"       # 상대방 준비 완료
    GAME_START = "game_start"           # 게임 시작
    GAME_STATE = "game_state"           # 게임 상태 업데이트
    TURN_CHANGE = "turn_change"         # 턴 변경
    TURN_TIMEOUT = "turn_timeout"       # 턴 시간 초과
    GAME_END = "game_end"               # 게임 종료
    ERROR = "error"                     # 에러


class WSMessage(BaseModel):
    """기본 WebSocket 메시지"""
    type: WSMessageType
    data: Optional[dict] = None


# ===== 클라이언트 → 서버 메시지 =====

class JoinQueueMessage(BaseModel):
    """랭킹전 매칭 큐 참가"""
    type: Literal["join_queue"] = "join_queue"


class CreateRoomMessage(BaseModel):
    """친구대전 방 생성"""
    type: Literal["create_room"] = "create_room"
    turn_time_limit: Optional[int] = Field(default=30, description="턴 제한 시간 (초), None이면 무제한")


class JoinRoomMessage(BaseModel):
    """친구대전 방 참가"""
    type: Literal["join_room"] = "join_room"
    room_code: str = Field(..., min_length=6, max_length=6)


class ReadyMessage(BaseModel):
    """준비 완료"""
    type: Literal["ready"] = "ready"


class MoveMessage(BaseModel):
    """폰 이동"""
    type: Literal["move"] = "move"
    row: int = Field(..., ge=0, le=8)
    col: int = Field(..., ge=0, le=8)


class WallMessage(BaseModel):
    """벽 설치"""
    type: Literal["wall"] = "wall"
    row: int = Field(..., ge=0, le=7)
    col: int = Field(..., ge=0, le=7)
    orientation: Literal["horizontal", "vertical"]


class SurrenderMessage(BaseModel):
    """항복"""
    type: Literal["surrender"] = "surrender"


# ===== 서버 → 클라이언트 메시지 =====

class ConnectedResponse(BaseModel):
    """연결 성공 응답"""
    type: Literal["connected"] = "connected"
    user_id: int
    nickname: str
    message: str = "WebSocket 연결 성공"


class QueueStatusResponse(BaseModel):
    """큐 상태 응답"""
    type: Literal["queue_status"] = "queue_status"
    position: int                    # 큐에서의 위치
    waiting_count: int               # 총 대기 인원
    estimated_wait: Optional[int]    # 예상 대기 시간 (초)


class MatchedResponse(BaseModel):
    """매칭 완료 응답"""
    type: Literal["matched"] = "matched"
    game_id: str
    opponent_nickname: str
    opponent_score: float
    you_are_player: int              # 1 또는 2
    message: str = "매칭 완료!"


class RoomCreatedResponse(BaseModel):
    """방 생성 완료 응답"""
    type: Literal["room_created"] = "room_created"
    room_code: str
    message: str = "방이 생성되었습니다. 친구에게 코드를 공유하세요."


class RoomJoinedResponse(BaseModel):
    """방 참가 완료 응답"""
    type: Literal["room_joined"] = "room_joined"
    room_code: str
    host_nickname: str
    you_are_player: int              # 1 (호스트) 또는 2 (게스트)
    message: str


class PlayerJoinedResponse(BaseModel):
    """상대방 입장 알림"""
    type: Literal["player_joined"] = "player_joined"
    player_nickname: str
    message: str


class GameStartResponse(BaseModel):
    """게임 시작 응답"""
    type: Literal["game_start"] = "game_start"
    game_id: str
    game_mode: str
    player1_nickname: str
    player2_nickname: str
    you_are_player: int
    turn_time_limit: Optional[int]   # 턴 제한 시간 (초)
    game_state: dict
    message: str = "게임이 시작되었습니다!"


class GameStateResponse(BaseModel):
    """게임 상태 업데이트"""
    type: Literal["game_state"] = "game_state"
    game_state: dict
    last_action: Optional[dict] = None
    current_turn: int
    turn_time_remaining: Optional[int] = None


class TurnChangeResponse(BaseModel):
    """턴 변경 알림"""
    type: Literal["turn_change"] = "turn_change"
    current_turn: int
    your_turn: bool
    turn_time_limit: Optional[int]
    message: str


class GameEndResponse(BaseModel):
    """게임 종료"""
    type: Literal["game_end"] = "game_end"
    winner: int                      # 1 또는 2
    winner_nickname: str
    reason: str                      # "goal_reached", "surrender", "timeout", "disconnect"
    final_state: dict
    score_change: Optional[float] = None  # 랭킹전일 경우
    new_rank: Optional[int] = None        # 랭킹전일 경우
    message: str


class ErrorResponse(BaseModel):
    """에러 응답"""
    type: Literal["error"] = "error"
    code: str
    message: str
