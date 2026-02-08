# 쿼리도(Quoridor) 게임 스키마

## 개요

게임 상태의 직렬화/역직렬화 및 DB 저장을 위한 스키마 정의입니다.

---

## 게임 상태 스키마 (GameState)

### JSON 스키마

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "title": "QuoridorGameState",
  "type": "object",
  "required": ["game_id", "status", "game_mode", "current_turn", "turn_count", "players", "walls"],
  "properties": {
    "game_id": {
      "type": "string",
      "format": "uuid",
      "description": "게임 고유 식별자"
    },
    "status": {
      "type": "string",
      "enum": ["in_progress", "player1_win", "player2_win", "abandoned"],
      "description": "게임 상태"
    },
    "game_mode": {
      "type": "string",
      "enum": ["vs_ai", "local_2p"],
      "description": "게임 모드"
    },
    "current_turn": {
      "type": "integer",
      "enum": [1, 2],
      "description": "현재 턴인 플레이어"
    },
    "turn_count": {
      "type": "integer",
      "minimum": 0,
      "description": "총 진행된 턴 수"
    },
    "players": {
      "type": "object",
      "required": ["player1", "player2"],
      "properties": {
        "player1": { "$ref": "#/definitions/Player" },
        "player2": { "$ref": "#/definitions/Player" }
      }
    },
    "walls": {
      "type": "array",
      "items": { "$ref": "#/definitions/Wall" },
      "description": "설치된 벽 목록"
    },
    "winner": {
      "type": ["integer", "null"],
      "enum": [1, 2, null],
      "description": "승자 (게임 종료 시)"
    },
    "created_at": {
      "type": "string",
      "format": "date-time"
    },
    "updated_at": {
      "type": "string",
      "format": "date-time"
    }
  },
  "definitions": {
    "Position": {
      "type": "object",
      "required": ["row", "col"],
      "properties": {
        "row": { "type": "integer", "minimum": 0, "maximum": 8 },
        "col": { "type": "integer", "minimum": 0, "maximum": 8 }
      }
    },
    "Player": {
      "type": "object",
      "required": ["name", "position", "walls_remaining", "goal_row"],
      "properties": {
        "name": { "type": "string" },
        "position": { "$ref": "#/definitions/Position" },
        "walls_remaining": { "type": "integer", "minimum": 0, "maximum": 10 },
        "goal_row": { "type": "integer", "enum": [0, 8] }
      }
    },
    "Wall": {
      "type": "object",
      "required": ["row", "col", "orientation"],
      "properties": {
        "row": { "type": "integer", "minimum": 0, "maximum": 7 },
        "col": { "type": "integer", "minimum": 0, "maximum": 7 },
        "orientation": { "type": "string", "enum": ["horizontal", "vertical"] }
      }
    }
  }
}
```

---

## 상태 값 정의

### GameStatus

| 값 | 설명 |
|----|------|
| `in_progress` | 게임 진행 중 |
| `player1_win` | Player 1 승리 |
| `player2_win` | Player 2 / AI 승리 |
| `abandoned` | 게임 포기 |

### GameMode

| 값 | 설명 |
|----|------|
| `vs_ai` | AI 대전 |
| `local_2p` | 로컬 2인 대전 |

### ActionType

| 값 | 설명 |
|----|------|
| `move` | 폰 이동 |
| `wall` | 벽 설치 |

---

## DB 모델

### GameSession 테이블

게임 세션 정보를 저장합니다.

| 컬럼 | 타입 | 설명 |
|------|------|------|
| `game_id` | VARCHAR(36) PK | 게임 ID (UUID) |
| `status` | ENUM | 게임 상태 |
| `game_mode` | ENUM | 게임 모드 |
| `player1_name` | VARCHAR(50) | Player 1 이름 |
| `player2_name` | VARCHAR(50) | Player 2 이름 |
| `current_turn` | INTEGER | 현재 턴 (1 또는 2) |
| `turn_count` | INTEGER | 총 턴 수 |
| `winner` | INTEGER NULL | 승자 |
| `ai_difficulty` | VARCHAR(20) NULL | AI 난이도 (vs_ai 모드) |
| `game_state` | JSONB | 전체 게임 상태 |
| `game_history` | JSONB | 히스토리 배열 (deprecated) |
| `created_at` | DATETIME | 생성 시간 |
| `updated_at` | DATETIME | 수정 시간 |
| `is_deleted` | BOOLEAN | 소프트 삭제 여부 |

### GameMove 테이블

각 수를 개별 레코드로 저장합니다 (리플레이용).

| 컬럼 | 타입 | 설명 |
|------|------|------|
| `id` | INTEGER PK | 자동 증가 ID |
| `game_id` | VARCHAR(36) FK | 게임 ID |
| `step_no` | INTEGER | 수 번호 (0부터) |
| `player` | INTEGER | 플레이어 (1 또는 2) |
| `action_type` | ENUM | 액션 타입 (move/wall) |
| `row` | INTEGER | 행 좌표 |
| `col` | INTEGER | 열 좌표 |
| `orientation` | VARCHAR(20) NULL | 벽 방향 |
| `game_state_snapshot` | JSONB | 수 이후 상태 스냅샷 |
| `created_at` | DATETIME | 기록 시간 |

---

## API 스키마

### 요청 (Request)

#### CreateGameRequest
```json
{
  "player1_name": "Player 1",
  "player2_name": "Player 2",
  "ai_difficulty": "normal",
  "game_mode": "vs_ai"
}
```

| 필드 | 타입 | 기본값 | 설명 |
|------|------|--------|------|
| `player1_name` | string | "Player 1" | Player 1 이름 |
| `player2_name` | string | "Player 2" | Player 2 이름 |
| `ai_difficulty` | enum | "normal" | easy, normal, hard |
| `game_mode` | enum | "vs_ai" | vs_ai, local_2p |

#### MoveRequest
```json
{
  "row": 7,
  "col": 4
}
```

#### WallRequest
```json
{
  "row": 4,
  "col": 3,
  "orientation": "horizontal"
}
```

### 응답 (Response)

#### ActionResponse
```json
{
  "success": true,
  "game_state": { ... },
  "message": "Move successful",
  "error": null
}
```

#### AIActionResponse
```json
{
  "success": true,
  "action": {
    "type": "move",
    "row": 1,
    "col": 4,
    "orientation": null
  },
  "game_state": { ... },
  "message": "AI moved pawn"
}
```

#### ValidMovesResponse
```json
{
  "valid_pawn_moves": [
    {"row": 7, "col": 4},
    {"row": 8, "col": 3}
  ],
  "valid_wall_placements": [
    {"row": 0, "col": 0, "orientation": "horizontal"}
  ],
  "walls_remaining": 8
}
```

---

## 리플레이 스키마

### MoveRecord
```json
{
  "step_no": 0,
  "player": 1,
  "action_type": "move",
  "row": 7,
  "col": 4,
  "orientation": null,
  "created_at": "2025-01-15T10:30:00Z"
}
```

### ReplayMovesResponse
```json
{
  "game_id": "550e8400-e29b-41d4-a716-446655440000",
  "moves": [ ... ],
  "total_moves": 25
}
```

### ReplayStateResponse
```json
{
  "game_id": "550e8400-e29b-41d4-a716-446655440000",
  "step_no": 5,
  "game_state": { ... },
  "is_initial": false
}
```

---

## 예시 데이터

### 초기 게임 상태

```json
{
  "game_id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "in_progress",
  "game_mode": "vs_ai",
  "current_turn": 1,
  "turn_count": 0,
  "players": {
    "player1": {
      "name": "Player",
      "position": {"row": 8, "col": 4},
      "walls_remaining": 10,
      "goal_row": 0
    },
    "player2": {
      "name": "AI",
      "position": {"row": 0, "col": 4},
      "walls_remaining": 10,
      "goal_row": 8
    }
  },
  "walls": [],
  "winner": null,
  "created_at": "2025-01-15T10:30:00Z",
  "updated_at": "2025-01-15T10:30:00Z"
}
```

### 종료된 게임 (Player 1 승리)

```json
{
  "game_id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "player1_win",
  "game_mode": "vs_ai",
  "current_turn": 1,
  "turn_count": 25,
  "players": {
    "player1": {
      "name": "Player",
      "position": {"row": 0, "col": 3},
      "walls_remaining": 5,
      "goal_row": 0
    },
    "player2": {
      "name": "AI",
      "position": {"row": 6, "col": 4},
      "walls_remaining": 4,
      "goal_row": 8
    }
  },
  "walls": [
    {"row": 1, "col": 2, "orientation": "horizontal"},
    {"row": 2, "col": 4, "orientation": "vertical"},
    {"row": 3, "col": 1, "orientation": "horizontal"}
  ],
  "winner": 1,
  "created_at": "2025-01-15T10:30:00Z",
  "updated_at": "2025-01-15T10:55:00Z"
}
```

---

## 좌표 시스템

### 보드 좌표 (9x9)
- 행/열: 0-8
- Player 1 시작: (8, 4), 목표: row 0
- Player 2 시작: (0, 4), 목표: row 8

### 벽 좌표 (8x8 교차점)
- 행/열: 0-7
- 벽 길이: 2칸

### 벽 차단 예시

```python
# 수평 벽 (row=3, col=4) -> (3,4)-(4,4), (3,5)-(4,5) 사이 차단
blocked = [
    ((3, 4), (4, 4)),
    ((3, 5), (4, 5))
]

# 수직 벽 (row=3, col=4) -> (3,4)-(3,5), (4,4)-(4,5) 사이 차단
blocked = [
    ((3, 4), (3, 5)),
    ((4, 4), (4, 5))
]
```
