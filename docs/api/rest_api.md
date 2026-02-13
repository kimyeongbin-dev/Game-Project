# 쿼리도(Quoridor) REST API 명세서

## Base URL
```
/api/v1/quoridor
```

---

## 엔드포인트 목록

| Method | Endpoint | 설명 |
|--------|----------|------|
| POST | `/games` | 새 게임 생성 |
| GET | `/games/{game_id}` | 게임 상태 조회 |
| POST | `/games/{game_id}/move` | 폰 이동 |
| POST | `/games/{game_id}/wall` | 벽 설치 |
| POST | `/games/{game_id}/ai-move` | AI 턴 요청 |
| GET | `/games/{game_id}/valid-moves` | 유효한 이동 목록 조회 |

---

## 상세 명세

### 1. 새 게임 생성

**POST** `/games`

새로운 쿼리도 게임을 생성합니다.

#### Request Body
```json
{
  "player_name": "Player1",
  "ai_difficulty": "normal"
}
```

| 필드 | 타입 | 필수 | 설명 |
|------|------|------|------|
| player_name | string | N | 플레이어 이름 (기본값: "Player") |
| ai_difficulty | string | N | AI 난이도: "easy", "normal", "hard" (기본값: "normal") |

#### Response (201 Created)
```json
{
  "game_id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "in_progress",
  "current_turn": 1,
  "message": "Game created successfully"
}
```

---

### 2. 게임 상태 조회

**GET** `/games/{game_id}`

현재 게임 상태를 조회합니다.

#### Path Parameters
| 파라미터 | 타입 | 설명 |
|----------|------|------|
| game_id | string (UUID) | 게임 고유 ID |

#### Response (200 OK)
```json
{
  "game_id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "in_progress",
  "current_turn": 1,
  "turn_count": 5,
  "players": {
    "player1": {
      "name": "Player1",
      "position": {"row": 6, "col": 4},
      "walls_remaining": 8,
      "goal_row": 0
    },
    "player2": {
      "name": "AI",
      "position": {"row": 2, "col": 4},
      "walls_remaining": 9,
      "goal_row": 8
    }
  },
  "walls": [
    {"row": 3, "col": 3, "orientation": "horizontal"},
    {"row": 5, "col": 4, "orientation": "vertical"}
  ],
  "winner": null,
  "created_at": "2025-01-15T10:30:00Z",
  "updated_at": "2025-01-15T10:35:00Z"
}
```

#### Response Fields

| 필드 | 타입 | 설명 |
|------|------|------|
| game_id | string | 게임 고유 ID |
| status | string | "in_progress", "finished" |
| current_turn | int | 현재 턴 플레이어 (1 또는 2) |
| turn_count | int | 총 턴 수 |
| players | object | 플레이어 정보 |
| walls | array | 설치된 벽 목록 |
| winner | int/null | 승자 (1, 2, 또는 null) |

---

### 3. 폰 이동

**POST** `/games/{game_id}/move`

현재 턴 플레이어의 폰을 이동합니다.

#### Request Body
```json
{
  "row": 7,
  "col": 4
}
```

| 필드 | 타입 | 필수 | 설명 |
|------|------|------|------|
| row | int | Y | 목표 행 (0-8) |
| col | int | Y | 목표 열 (0-8) |

#### Response (200 OK)
```json
{
  "success": true,
  "game_state": { /* 전체 게임 상태 */ },
  "message": "Pawn moved successfully"
}
```

#### Error Response (400 Bad Request)
```json
{
  "success": false,
  "error": "invalid_move",
  "message": "Cannot move to the specified position"
}
```

---

### 4. 벽 설치

**POST** `/games/{game_id}/wall`

현재 턴 플레이어가 벽을 설치합니다.

#### Request Body
```json
{
  "row": 4,
  "col": 3,
  "orientation": "horizontal"
}
```

| 필드 | 타입 | 필수 | 설명 |
|------|------|------|------|
| row | int | Y | 벽 시작 행 (0-7) |
| col | int | Y | 벽 시작 열 (0-7) |
| orientation | string | Y | "horizontal" 또는 "vertical" |

#### Response (200 OK)
```json
{
  "success": true,
  "game_state": { /* 전체 게임 상태 */ },
  "message": "Wall placed successfully"
}
```

#### Error Responses

**400 Bad Request - 벽이 없음**
```json
{
  "success": false,
  "error": "no_walls_remaining",
  "message": "No walls remaining"
}
```

**400 Bad Request - 유효하지 않은 위치**
```json
{
  "success": false,
  "error": "invalid_wall_position",
  "message": "Wall overlaps with existing wall"
}
```

**400 Bad Request - 경로 차단**
```json
{
  "success": false,
  "error": "path_blocked",
  "message": "Wall would block all paths to goal"
}
```

---

### 5. AI 턴 요청

**POST** `/games/{game_id}/ai-move`

AI가 자동으로 턴을 수행합니다.

#### Request Body
없음

#### Response (200 OK)
```json
{
  "success": true,
  "action": {
    "type": "move",
    "row": 1,
    "col": 4
  },
  "game_state": { /* 전체 게임 상태 */ },
  "message": "AI moved pawn"
}
```

또는 벽 설치 시:
```json
{
  "success": true,
  "action": {
    "type": "wall",
    "row": 5,
    "col": 3,
    "orientation": "horizontal"
  },
  "game_state": { /* 전체 게임 상태 */ },
  "message": "AI placed wall"
}
```

---

### 6. 유효한 이동 목록 조회

**GET** `/games/{game_id}/valid-moves`

현재 턴 플레이어가 수행할 수 있는 모든 유효한 행동을 조회합니다.

#### Response (200 OK)
```json
{
  "valid_pawn_moves": [
    {"row": 7, "col": 4},
    {"row": 8, "col": 3},
    {"row": 8, "col": 5}
  ],
  "valid_wall_placements": [
    {"row": 0, "col": 0, "orientation": "horizontal"},
    {"row": 0, "col": 0, "orientation": "vertical"},
    /* ... */
  ],
  "walls_remaining": 8
}
```

---

## 에러 코드

| 코드 | 에러 | 설명 |
|------|------|------|
| 400 | invalid_move | 유효하지 않은 폰 이동 |
| 400 | invalid_wall_position | 유효하지 않은 벽 위치 |
| 400 | no_walls_remaining | 남은 벽이 없음 |
| 400 | path_blocked | 벽이 경로를 완전히 차단 |
| 400 | not_your_turn | 자신의 턴이 아님 |
| 400 | game_finished | 이미 종료된 게임 |
| 404 | game_not_found | 게임을 찾을 수 없음 |

---

## 공통 응답 구조

### 성공 응답
```json
{
  "success": true,
  "data": { /* 응답 데이터 */ },
  "message": "설명 메시지"
}
```

### 에러 응답
```json
{
  "success": false,
  "error": "error_code",
  "message": "에러 설명"
}
```
