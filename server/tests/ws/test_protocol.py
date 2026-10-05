"""WS 봉투 — 파싱 규약, 고정 에러 문구, 어휘 집계 (maze.md §1·§12·§13)"""

import json
import re

import pytest

from app.games.maze.core.move_validator import Rejection
from app.schemas.ws_messages import (
    CLIENT_TYPES,
    PAYLOAD_MODELS,
    RETIRED_TYPES,
    SERVER_TYPES,
    WSMessageType,
)
from app.services.activity import _BUSY_CODES
from app.ws.protocol import (
    MESSAGES,
    ProtocolError,
    error_message,
    parse_envelope,
    parse_payload,
    server_message,
)


# ----- 어휘 (§12) -----

def test_vocabulary_is_25_with_one_retired():
    assert len(WSMessageType) == 25
    assert len(CLIENT_TYPES) == 10 and len(SERVER_TYPES) == 15
    assert RETIRED_TYPES == {WSMessageType.TURN_TIMEOUT}
    assert set(PAYLOAD_MODELS) == CLIENT_TYPES


# ----- 봉투 -----

def test_parse_valid_envelope():
    msg = parse_envelope(json.dumps({"type": "move", "seq": 12, "payload": {"row": 7, "col": 4}}))
    assert msg.type is WSMessageType.MOVE and msg.seq == 12
    assert parse_payload(msg).row == 7


def test_payload_and_seq_are_optional():
    msg = parse_envelope('{"type": "leave_queue"}')
    assert msg.seq is None and msg.payload == {}


@pytest.mark.parametrize("raw, ack", [
    ("not json", None),
    ("[1, 2]", None),
    ('{"type": "move", "seq": "12"}', None),          # seq 는 정수만
    ('{"type": "move", "seq": true}', None),          # bool 은 정수가 아니다
    ('{"type": "fly", "seq": 3}', 3),                 # 없는 타입
    ('{"type": "game_state", "seq": 4}', 4),          # 서버 → 클라이언트 타입
    ('{"type": "turn_timeout", "seq": 5}', 5),        # 폐기 타입
    ('{"type": "move", "seq": 6, "payload": [1]}', 6),
])
def test_bad_envelope_is_invalid_request(raw, ack):
    with pytest.raises(ProtocolError) as err:
        parse_envelope(raw)
    assert err.value.code == "invalid_request"
    assert err.value.ack_seq == ack


@pytest.mark.parametrize("payload", [
    {"row": "7", "col": 4},     # 문자열 숫자
    {"row": 7.0, "col": 4},     # 실수
    {"row": True, "col": 4},    # bool
    {"col": 4},                 # 누락
])
def test_move_payload_types_only(payload):
    msg = parse_envelope(json.dumps({"type": "move", "seq": 1, "payload": payload}))
    with pytest.raises(ProtocolError) as err:
        parse_payload(msg)
    assert err.value.code == "invalid_request" and err.value.ack_seq == 1


def test_out_of_range_coordinates_pass_to_engine():
    """범위 판정은 엔진 몫이다 — §7 '범위 밖은 거절 카운터에 세지 않는다'를 엔진이 지킨다"""
    msg = parse_envelope('{"type": "wall", "payload": {"row": 99, "col": -1, "orientation": "diagonal"}}')
    wall = parse_payload(msg)
    assert (wall.row, wall.col, wall.orientation) == (99, -1, "diagonal")


def test_undeclared_fields_are_dropped():
    """페이로드의 seat_no·user_id·시각은 모델에 없다 — 서버가 읽을 방법이 없다"""
    msg = parse_envelope(json.dumps({"type": "move", "payload": {
        "row": 1, "col": 2, "seat_no": 3, "user_id": 99, "remaining_ms": 999999, "received_at": 0,
    }}))
    move = parse_payload(msg)
    assert move.model_dump() == {"row": 1, "col": 2}


# ----- 에러 (§1·§13) -----

def test_every_service_code_has_a_message():
    """엔진 거절·활동 충돌 코드는 전부 고정 문구가 있다 — 없으면 internal_error 로 뭉개진다"""
    for code in [r.value for r in Rejection] + list(_BUSY_CODES.values()):
        assert code in MESSAGES, code


def test_messages_have_no_placeholders_or_digits():
    """문구는 고정이다 — 포맷 자리·숫자(좌표처럼 보일 수 있는 것)가 없다"""
    for code, text in MESSAGES.items():
        assert not re.search(r"[{}%\d]", text), code


def test_error_envelope():
    assert error_message("not_your_turn", 12) == {
        "type": "error", "ack_seq": 12,
        "payload": {"error": "not_your_turn", "message": "내 차례가 아닙니다."},
    }


def test_unknown_code_becomes_internal_error():
    """표에 없는 코드(예외 문구가 코드 자리에 들어간 경우 포함)는 그대로 나가지 않는다"""
    err = error_message("Wall at (3, 5) overlaps", 1)
    assert err["payload"] == {"error": "internal_error", "message": MESSAGES["internal_error"]}


def test_server_message_envelope():
    assert server_message(WSMessageType.QUEUE_STATUS, {"position": 1}) == {
        "type": "queue_status", "payload": {"position": 1},
    }
    assert server_message(WSMessageType.GAME_STATE, {}, ack_seq=3, version=9) == {
        "type": "game_state", "payload": {}, "ack_seq": 3, "version": 9,
    }
