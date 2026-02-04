# 쿼리도(Quoridor) 게임 상태 JSON 스키마

## 개요

게임 상태의 직렬화/역직렬화를 위한 JSON 스키마 정의입니다.

---

## 전체 게임 상태 스키마

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "title": "QuoridorGameState",
  "type": "object",
  "required": ["game_id", "status", "current_turn", "turn_count", "players", "walls"],
  "properties": {
    "game_id": {
      "type": "string",
      "format": "uuid",
      "description": "게임 고유 식별자"
    },
    "status": {
      "type": "string",
      "enum": ["in_progress", "finished"],
      "description": "게임 진행 상태"
    },
    "current_turn": {
      "type": "integer",
      "enum": [1, 2],
      "description": "현재 턴인 플레이어 (1 또는 2)"
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
      "format": "date-time",
      "description": "게임 생성 시간"
    },
    "updated_at": {
      "type": "string",
      "format": "date-time",
      "description": "마지막 업데이트 시간"
    }
  },
  "definitions": {
    "Position": {
      "type": "object",
      "required": ["row", "col"],
      "properties": {
        "row": {
          "type": "integer",
          "minimum": 0,
          "maximum": 8,
          "description": "행 좌표 (0-8)"
        },
        "col": {
          "type": "integer",
          "minimum": 0,
          "maximum": 8,
          "description": "열 좌표 (0-8)"
        }
      }
    },
    "Player": {
      "type": "object",
      "required": ["name", "position", "walls_remaining", "goal_row"],
      "properties": {
        "name": {
          "type": "string",
          "description": "플레이어 이름"
        },
        "position": {
          "$ref": "#/definitions/Position",
          "description": "현재 폰 위치"
        },
        "walls_remaining": {
          "type": "integer",
          "minimum": 0,
          "maximum": 10,
          "description": "남은 벽 개수"
        },
        "goal_row": {
          "type": "integer",
          "enum": [0, 8],
          "description": "목표 행 (도달 시 승리)"
        }
      }
    },
    "Wall": {
      "type": "object",
      "required": ["row", "col", "orientation"],
      "properties": {
        "row": {
          "type": "integer",
          "minimum": 0,
          "maximum": 7,
          "description": "벽 시작 행 좌표 (0-7)"
        },
        "col": {
          "type": "integer",
          "minimum": 0,
          "maximum": 7,
          "description": "벽 시작 열 좌표 (0-7)"
        },
        "orientation": {
          "type": "string",
          "enum": ["horizontal", "vertical"],
          "description": "벽 방향"
        }
      }
    }
  }
}
```

---

## 예시 데이터

### 초기 게임 상태

```json
{
  "game_id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "in_progress",
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

### 진행 중인 게임 상태

```json
{
  "game_id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "in_progress",
  "current_turn": 2,
  "turn_count": 12,
  "players": {
    "player1": {
      "name": "Player",
      "position": {"row": 4, "col": 5},
      "walls_remaining": 7,
      "goal_row": 0
    },
    "player2": {
      "name": "AI",
      "position": {"row": 5, "col": 4},
      "walls_remaining": 6,
      "goal_row": 8
    }
  },
  "walls": [
    {"row": 3, "col": 3, "orientation": "horizontal"},
    {"row": 3, "col": 5, "orientation": "horizontal"},
    {"row": 5, "col": 2, "orientation": "vertical"},
    {"row": 6, "col": 4, "orientation": "horizontal"},
    {"row": 2, "col": 6, "orientation": "vertical"},
    {"row": 4, "col": 1, "orientation": "vertical"},
    {"row": 7, "col": 3, "orientation": "horizontal"}
  ],
  "winner": null,
  "created_at": "2025-01-15T10:30:00Z",
  "updated_at": "2025-01-15T10:42:00Z"
}
```

### 종료된 게임 상태

```json
{
  "game_id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "finished",
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
    {"row": 3, "col": 1, "orientation": "horizontal"},
    {"row": 4, "col": 5, "orientation": "vertical"},
    {"row": 5, "col": 3, "orientation": "horizontal"},
    {"row": 6, "col": 2, "orientation": "vertical"},
    {"row": 7, "col": 4, "orientation": "horizontal"},
    {"row": 1, "col": 6, "orientation": "vertical"},
    {"row": 3, "col": 6, "orientation": "horizontal"},
    {"row": 5, "col": 0, "orientation": "vertical"},
    {"row": 2, "col": 0, "orientation": "horizontal"}
  ],
  "winner": 1,
  "created_at": "2025-01-15T10:30:00Z",
  "updated_at": "2025-01-15T10:55:00Z"
}
```

---

## 내부 저장 형식

### 벽 교차 확인용 블록 좌표

벽은 2칸을 차단하므로, 교차 검사를 위해 내부적으로 "블록된 셀 경계" 목록을 유지합니다.

```python
# 수평 벽 (row=3, col=4) 설치 시 차단되는 경계
blocked_edges = [
    ((3, 4), (4, 4)),  # (3,4)에서 (4,4)로 이동 불가
    ((4, 4), (3, 4)),  # 역방향도 불가
    ((3, 5), (4, 5)),  # (3,5)에서 (4,5)로 이동 불가
    ((4, 5), (3, 5)),  # 역방향도 불가
]

# 수직 벽 (row=3, col=4) 설치 시 차단되는 경계
blocked_edges = [
    ((3, 4), (3, 5)),  # (3,4)에서 (3,5)로 이동 불가
    ((3, 5), (3, 4)),  # 역방향도 불가
    ((4, 4), (4, 5)),  # (4,4)에서 (4,5)로 이동 불가
    ((4, 5), (4, 4)),  # 역방향도 불가
]
```

---

## 액션 스키마

### 폰 이동 액션

```json
{
  "type": "move",
  "row": 7,
  "col": 4
}
```

### 벽 설치 액션

```json
{
  "type": "wall",
  "row": 4,
  "col": 3,
  "orientation": "horizontal"
}
```

---

## 유효한 행동 목록 스키마

```json
{
  "valid_pawn_moves": [
    {"row": 7, "col": 4},
    {"row": 8, "col": 3},
    {"row": 8, "col": 5}
  ],
  "valid_wall_placements": [
    {"row": 0, "col": 0, "orientation": "horizontal"},
    {"row": 0, "col": 0, "orientation": "vertical"}
  ],
  "walls_remaining": 8
}
```
