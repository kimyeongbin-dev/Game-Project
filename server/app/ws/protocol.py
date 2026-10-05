"""
WS 봉투 — 파싱, 에러, 서버 메시지, close code (maze.md §1·§2·§13)

- 클라이언트 → 서버: `{type, seq?, payload?}`. `seq` 는 요청 번호이고 응답·에러의 `ack_seq` 로 되돌아간다
- 서버 → 클라이언트: `{type, payload, ack_seq?, version?}`. `version` 은 게임 범위 메시지의 게임별 단조 번호다(L23)
- **에러 문구는 아래 고정 표에서만 나온다.** 예외 문구(엔진 `ValueError` 에는 좌표가 있다)를 소켓에 싣지 않는다.
  표에 없는 코드는 `internal_error` 로 바꾼다 — 새 코드가 문구 없이 새어 나가지 않는다
"""

import json
from dataclasses import dataclass, field
from typing import Any, Optional

from pydantic import ValidationError

from app.schemas.ws_messages import CLIENT_TYPES, PAYLOAD_MODELS, WSMessageType

# ----- close code (§13 "연결 종료 코드") -----
CLOSE_REPLACED = 4000           # 같은 계정의 새 연결이 들어왔다
CLOSE_INVALID_TOKEN = 4001      # 토큰 없음·무효·만료·access 아님
CLOSE_LOGIN_REQUIRED = 4002     # 익명 계정
CLOSE_NICKNAME_REQUIRED = 4003  # 닉네임 미설정
CLOSE_POLICY_VIOLATION = 1008   # 레이트 리밋을 계속 넘겼다 (표준 코드)
CLOSE_TRY_AGAIN_LATER = 1013    # 접속 연타·실시간 저장소 없음 (표준 코드)

# ----- 에러 코드 → 고정 문구 -----
MESSAGES: dict[str, str] = {
    # §13 게임 전용
    "login_required": "로그인이 필요합니다.",
    "nickname_required": "닉네임을 먼저 설정해 주세요.",
    "already_in_queue": "이미 매칭 대기 중입니다.",
    "already_in_room": "이미 방에 있습니다.",
    "already_in_game": "진행 중인 게임이 있습니다.",
    "not_in_queue": "매칭 대기 중이 아닙니다.",
    "not_in_room": "방에 있지 않습니다.",
    "not_in_game": "게임에 참여하고 있지 않습니다.",
    "room_not_found": "방을 찾을 수 없습니다.",
    "room_full": "방이 가득 찼습니다.",
    "not_your_turn": "내 차례가 아닙니다.",
    "invalid_move": "이동할 수 없는 칸입니다.",
    "invalid_wall_position": "벽을 놓을 수 없는 자리입니다.",
    "no_walls_remaining": "남은 벽이 없습니다.",
    "wall_blocks_path": "누군가의 길을 완전히 막는 벽입니다.",
    "probe_limit_exceeded": "이번 턴에는 더 이상 벽을 놓을 수 없습니다.",
    "game_already_ended": "이미 끝난 게임입니다.",
    "server_busy": "잠시 후 다시 시도해 주세요.",
    # platform.md §0 공통
    "invalid_request": "요청 형식이 올바르지 않습니다.",
    "feature_disabled": "아직 제공하지 않는 기능입니다.",
    "rate_limit_exceeded": "요청이 너무 많습니다. 잠시 후 다시 시도해주세요.",
    "internal_error": "서버 오류가 발생했습니다.",
}


@dataclass(frozen=True)
class ClientMessage:
    type: WSMessageType
    seq: Optional[int]
    payload: dict = field(default_factory=dict)


class ProtocolError(Exception):
    """봉투·페이로드가 규약에 맞지 않는다. code 는 MESSAGES 의 키"""

    def __init__(self, code: str, ack_seq: Optional[int] = None):
        super().__init__(code)
        self.code = code
        self.ack_seq = ack_seq


def _strict_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def parse_envelope(raw: str) -> ClientMessage:
    """텍스트 프레임 하나 → ClientMessage. 규약 위반은 ProtocolError(invalid_request)"""
    try:
        data = json.loads(raw)
    except (TypeError, ValueError):
        raise ProtocolError("invalid_request") from None
    if not isinstance(data, dict):
        raise ProtocolError("invalid_request")

    seq = data.get("seq")
    if seq is not None and not _strict_int(seq):
        raise ProtocolError("invalid_request")

    try:
        type_ = WSMessageType(data.get("type"))
    except ValueError:
        raise ProtocolError("invalid_request", seq) from None
    if type_ not in CLIENT_TYPES:  # 서버 → 클라이언트 타입을 보내 왔다
        raise ProtocolError("invalid_request", seq)

    payload = data.get("payload", {})
    if payload is None:
        payload = {}
    if not isinstance(payload, dict):
        raise ProtocolError("invalid_request", seq)
    return ClientMessage(type_, seq, payload)


def parse_payload(message: ClientMessage):
    """타입별 페이로드 모델. 정의되지 않은 필드는 버린다"""
    try:
        return PAYLOAD_MODELS[message.type].model_validate(message.payload)
    except ValidationError:
        raise ProtocolError("invalid_request", message.seq) from None


def server_message(
    type_: WSMessageType,
    payload: Optional[dict] = None,
    *,
    ack_seq: Optional[int] = None,
    version: Optional[int] = None,
) -> dict:
    message: dict = {"type": type_.value, "payload": payload if payload is not None else {}}
    if ack_seq is not None:
        message["ack_seq"] = ack_seq
    if version is not None:
        message["version"] = version
    return message


def error_message(code: str, ack_seq: Optional[int] = None) -> dict:
    """§1 에러 봉투. 표에 없는 코드는 internal_error — 문구는 언제나 표에서"""
    if code not in MESSAGES:
        code = "internal_error"
    return {
        "type": WSMessageType.ERROR.value,
        "ack_seq": ack_seq,
        "payload": {"error": code, "message": MESSAGES[code]},
    }
