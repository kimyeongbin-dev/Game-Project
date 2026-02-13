# WebSocket Protocol Documentation

## 개요
쿼리도 온라인 대전에서 사용하는 WebSocket 통신 프로토콜입니다.

## 연결
```
ws://{server}/ws/game?token={session_token}
```

## 메시지 형식
모든 메시지는 JSON 형식:
```json
{"type": "message_type", ...}
```

---

## 클라이언트 → 서버 메시지

### join_queue
랭킹전 매칭 큐 참가
```json
{"type": "join_queue"}
```

### leave_queue
매칭 큐 나가기
```json
{"type": "leave_queue"}
```

### create_room
친구대전 방 생성
```json
{"type": "create_room", "turn_time_limit": 30}
```

### join_room
친구대전 방 참가
```json
{"type": "join_room", "room_code": "ABCD"}
```

### leave_room
방 나가기
```json
{"type": "leave_room"}
```

### ready
준비 완료 (친구대전)
```json
{"type": "ready"}
```

### move
폰 이동
```json
{"type": "move", "row": 5, "col": 4}
```

### wall
벽 설치
```json
{"type": "wall", "row": 3, "col": 2, "orientation": "horizontal"}
```
- orientation: "horizontal" 또는 "vertical"

### surrender
항복
```json
{"type": "surrender"}
```

---

## 서버 → 클라이언트 메시지

### connected
WebSocket 연결 성공
```json
{
  "type": "connected",
  "user_id": 123,
  "nickname": "Player1",
  "message": "WebSocket 연결 성공"
}
```

### queue_joined
큐 참가 성공
```json
{
  "type": "queue_joined",
  "position": 1,
  "message": "매칭 큐에 참가했습니다"
}
```

### queue_status
큐 상태 업데이트
```json
{
  "type": "queue_status",
  "position": 1,
  "total_in_queue": 5,
  "estimated_wait": 30
}
```

### queue_left
큐 나가기 성공
```json
{
  "type": "queue_left",
  "message": "매칭 큐에서 나왔습니다"
}
```

### match_found
매칭 완료 (게임 시작 전)
```json
{
  "type": "match_found",
  "game_id": "uuid-string",
  "opponent_nickname": "Player2",
  "opponent_score": 100.5,
  "you_are_player": 1,
  "message": "매칭 완료!"
}
```

### room_created
방 생성 성공
```json
{
  "type": "room_created",
  "room_code": "ABCD",
  "turn_time_limit": 30,
  "message": "방이 생성되었습니다"
}
```

### room_joined
방 참가 성공
```json
{
  "type": "room_joined",
  "room_code": "ABCD",
  "host_nickname": "Player1",
  "you_are_player": 2,
  "turn_time_limit": 30,
  "message": "방에 참가했습니다"
}
```

### player_joined
상대방 입장 (호스트에게)
```json
{
  "type": "player_joined",
  "player_nickname": "Player2",
  "message": "Player2님이 입장했습니다"
}
```

### player_ready
상대방 준비 완료
```json
{
  "type": "player_ready",
  "player_nickname": "Player2",
  "message": "Player2님이 준비 완료했습니다"
}
```

### room_left
방 나가기 성공
```json
{
  "type": "room_left",
  "message": "방에서 나왔습니다"
}
```

### player_left
상대방 퇴장
```json
{
  "type": "player_left",
  "player_nickname": "Player2",
  "room_closed": true,
  "message": "Player2님이 나갔습니다"
}
```

### game_start
게임 시작 (매칭/준비 완료 후)
```json
{
  "type": "game_start",
  "game_id": "uuid-string",
  "game_mode": "ranked",
  "player1_nickname": "Player1",
  "player2_nickname": "Player2",
  "you_are_player": 1,
  "turn_time_limit": 30,
  "game_state": {
    "game_id": "uuid-string",
    "status": "in_progress",
    "game_mode": "ranked",
    "current_turn": 1,
    "turn_count": 0,
    "players": {
      "player1": {
        "name": "Player1",
        "position": {"row": 8, "col": 4},
        "walls_remaining": 10,
        "goal_row": 0
      },
      "player2": {
        "name": "Player2",
        "position": {"row": 0, "col": 4},
        "walls_remaining": 10,
        "goal_row": 8
      }
    },
    "walls": [],
    "winner": null,
    "created_at": "2024-01-01T00:00:00Z",
    "updated_at": "2024-01-01T00:00:00Z"
  },
  "message": "게임이 시작되었습니다!"
}
```

### game_state
게임 상태 업데이트 (액션 후)
```json
{
  "type": "game_state",
  "game_state": { /* 위 game_start의 game_state와 동일 구조 */ },
  "last_action": {
    "type": "move",
    "row": 7,
    "col": 4,
    "player": 1
  },
  "current_turn": 2,
  "your_turn": false
}
```

**중요**: `game_state` 메시지를 파싱할 때, 중첩된 `game_state` 필드를 추출해야 합니다!

### game_end
게임 종료
```json
{
  "type": "game_end",
  "winner": 1,
  "winner_nickname": "Player1",
  "reason": "goal_reached",
  "final_state": { /* game_state 구조 */ },
  "you_win": true,
  "message": "승리했습니다!",
  "score_change": 3.5,
  "new_rank": 15
}
```
- reason: "goal_reached", "surrender", "disconnect", "timeout"
- score_change, new_rank: 랭킹전에서만 포함

### error
에러 메시지
```json
{
  "type": "error",
  "code": "invalid_move",
  "message": "Invalid move"
}
```

에러 코드:
- `invalid_message`: 잘못된 메시지 형식
- `not_your_turn`: 상대방 턴
- `invalid_move`: 유효하지 않은 이동
- `invalid_wall`: 유효하지 않은 벽 설치
- `not_in_game`: 게임 중이 아님
- `game_not_found`: 게임을 찾을 수 없음
- `already_in_queue`: 이미 큐에 있음
- `not_in_queue`: 큐에 없음
- `room_error`: 방 관련 에러

---

## 파일 참조
- 서버 핸들러: `backend_fastapi/routers/ws_game.py`
- 클라이언트 서비스: `frontend_flutter/lib/services/websocket_service.dart`
- 게임 상태 모델 (서버): `games/game_Quoridor/core/game_state.py`
- 게임 상태 모델 (클라이언트): `frontend_flutter/lib/models/game_state.dart`
