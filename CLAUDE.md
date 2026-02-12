# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

A multi-platform game application featuring Quoridor (board game) with AI opponent. Built with Flutter frontend and FastAPI backend, supporting PostgreSQL with fallback to memory-only mode.

## Development Commands

### Backend (FastAPI)
```bash
# Activate conda environment first (required for all commands)
E:/Conda/Scripts/activate && conda activate GameProject

# Install dependencies
pip install -r backend_fastapi/requirements.txt

# Run server (from backend_fastapi directory)
cd backend_fastapi && uvicorn main:app --reload

# Run tests
pytest
```

### Frontend (Flutter)
```bash
cd frontend_flutter
flutter pub get
flutter run -d chrome    # Web (개발 모드, Hot Reload)
flutter run -d windows   # Windows desktop

# 로컬 테스트 서버 모드 (release 빌드, 모바일 기기 테스트용)
flutter run -d web-server --web-port=3000 --release
```

### 로컬 개발 테스트 환경
로컬 서버 + Docker DB + Flutter로 테스트할 때:

**1. Docker PostgreSQL (DB만 사용)**
```bash
docker compose up db -d
```

**2. 백엔드 서버 (로컬)**
```bash
cd backend_fastapi
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

**3. 프론트엔드 (로컬 web-server)**
```bash
cd frontend_flutter
flutter run -d web-server --web-port=3000 --release
```

**접속:**
- 노트북: `http://localhost:3000`
- 모바일: `http://{노트북IP}:3000` (예: `http://192.168.0.16:3000`)

**동작 방식:**
- `flutter run -d web-server`: Flutter 개발 서버가 포트 3000에서 웹 앱 제공
- `--release`: 최적화된 빌드로 모바일에서도 빠른 로딩
- `--host 0.0.0.0`: 외부 네트워크에서 접속 가능

**실시간 동기화:**
- 코드 수정 시 Hot Reload 지원 (`r` 키 또는 저장)
- `--release` 모드는 Hot Reload 미지원 (다시 빌드 필요)
- 개발 중 빠른 테스트는 `flutter run -d chrome` 권장 (Hot Reload 지원)

**vs Docker 정적 배포:**
| 항목 | `flutter run -d web-server` | Docker + static files |
|------|-----------------------------|-----------------------|
| 코드 수정 | Hot Reload (release 제외) | 매번 빌드 필요 |
| 용도 | 로컬 개발/테스트 | 배포/프로덕션 |
| 속도 | 빠름 | 초기 빌드 느림 |

### Database
- PostgreSQL required for persistence, but server gracefully degrades to memory-only mode
- Set `DB_ENABLED=false` env var to disable DB
- Default connection: `postgresql+asyncpg://postgres:postgres@localhost:5432/quoridor_db`

## Architecture

### Three-Layer Game Structure
1. **Game Engine** (`games/`): Pure Python game logic, no framework dependencies
   - `games/game_Quoridor/core/`: Board, Player, Wall, GameState, MoveValidator, Pathfinder
   - `games/game_Quoridor/ai/`: SimpleAI with difficulty levels

2. **Backend API** (`backend_fastapi/`): FastAPI REST layer
   - `services/quoridor_service.py`: Business logic, manages game instances in memory + DB
   - `routers/quoridor.py`: REST endpoints
   - `database/`: PostgreSQL via SQLAlchemy async

3. **Frontend** (`frontend_flutter/`): Flutter multi-platform UI
   - `lib/services/api_service.dart`: Backend communication
   - `lib/screens/quoridor_screen.dart`: Game screen
   - `lib/widgets/`: Board rendering components

### Key Design Patterns
- **Game State Serialization**: `GameState.to_dict()` / `GameState.from_dict()` for DB persistence
- **Graceful Degradation**: Server runs without DB (memory-only), `is_db_available()` checks before DB ops
- **Service Singleton**: `quoridor_service` instance manages all game state

## Quoridor Game Coordinates
- Board: 9x9 grid (0-8)
- Walls: 2-cell length, placed at intersections (0-7 range)
- Player 1 starts at (8,4), goal row 0
- Player 2/AI starts at (0,4), goal row 8

## API Base Path
`/api/v1/quoridor` - See `docs/quoridor/api_spec.md` for full specification

## Logging Guidelines

### Log Levels
- **DEBUG**: 모든 로그 (SQL 쿼리 포함) - 디버깅용
- **INFO**: 핵심 비즈니스 로직만 - 개발용 (기본값)
- **WARNING**: 경고/에러만 - 배포용

### INFO 레벨 로그 규칙
새로운 기능을 구현할 때 반드시 INFO 레벨 로그를 추가해야 합니다.

**필수 로깅 대상:**
- 사용자 인증: 회원가입, 로그인, 로그아웃
- 게임 이벤트: 게임 생성, 시작, 종료, 포기
- 매칭 시스템: 대기열 참가/나가기, 매칭 완료
- 게임 액션: 말 이동, 벽 설치, 항복
- 방 관리: 방 생성, 참가, 나가기, 준비 완료

**로그 형식:**
```python
import logging
logger = logging.getLogger(__name__)

# 형식: [기능명] 주요정보 (부가정보)
logger.info(f"[회원가입] {user.nickname}")
logger.info(f"[게임 생성] {user.nickname} (모드: {game_mode}, 게임: {game_id[:8]})")
logger.info(f"[말 이동] {user.nickname} -> ({row}, {col}) (게임: {game_id[:8]})")
logger.info(f"[대기열 참가] {user.nickname} (위치: {position})")
```

**주의사항:**
- game_id는 처음 8자리만 표시 (`game_id[:8]`)
- SQLAlchemy 및 연결 로그는 INFO에서 표시하지 않음
- WebSocket 연결/해제는 이미 로깅됨

## WebSocket 통신 규칙 (Client ↔ Server)

### 메시지 형식
서버와 클라이언트 모두 동일한 JSON 형식을 사용합니다:
```json
{"type": "message_type", "key1": "value1", "key2": "value2"}
```

### 메시지 타입 매핑 (반드시 일치해야 함)

| 기능 | 클라이언트 → 서버 | 서버 → 클라이언트 |
|------|-------------------|-------------------|
| 큐 참가 | `join_queue` | `queue_joined`, `queue_status` |
| 큐 나가기 | `leave_queue` | `queue_left` |
| 매칭 완료 | - | `match_found` |
| 방 생성 | `create_room` | `room_created` |
| 방 참가 | `join_room` | `room_joined` |
| 방 나가기 | `leave_room` | `room_left`, `player_left` |
| 준비 완료 | `ready` | `player_ready` |
| 게임 시작 | - | `game_start` |
| 말 이동 | `move` | `game_state` |
| 벽 설치 | `wall` | `game_state` |
| 항복 | `surrender` | `game_end` |
| 게임 종료 | - | `game_end` |
| 에러 | - | `error` |

### 중요: 중첩 데이터 파싱

서버가 `game_state` 메시지를 보낼 때 중첩 구조를 사용합니다:
```json
{
  "type": "game_state",
  "game_state": { /* 실제 게임 상태 데이터 */ },
  "last_action": { "type": "move", "row": 5, "col": 4 },
  "current_turn": 2,
  "your_turn": false
}
```

**클라이언트에서 파싱 시:**
```dart
// ❌ 잘못된 방법
onGameStateUpdate?.call(message.data);  // 전체 메시지 전달

// ✅ 올바른 방법
final gameStateData = message.data['game_state'] as Map<String, dynamic>?;
if (gameStateData != null) {
  onGameStateUpdate?.call(gameStateData);  // 중첩된 game_state만 전달
}
```

### game_end 메시지 구조
```json
{
  "type": "game_end",
  "winner": 1,
  "reason": "goal_reached",
  "final_state": { "turn_count": 25, ... },
  "score_change": 3.5,
  "new_rank": 15
}
```
- `turn_count`는 `final_state` 내부에 있음

### 수정 시 체크리스트
새 메시지 타입 추가 또는 수정 시:
1. **서버 (`ws_game.py`)**: `handle_message()` 함수에 핸들러 추가
2. **클라이언트 (`websocket_service.dart`)**:
   - `WsMessageType` 클래스에 상수 추가
   - `_handleMessage()` 함수에 case 추가
   - 필요시 전송 메서드 추가 (예: `movePawn()`)
3. **양쪽 타입명 일치 확인**: 서버와 클라이언트가 동일한 문자열 사용
4. **중첩 데이터 확인**: 서버가 중첩 구조로 보내면 클라이언트에서 올바르게 추출

### 디버깅 팁
- Flutter: `debugPrint('[WebSocket] received: ${message.type}')` 추가
- Server: `logger.info(f"[WS] {msg_type}: {user.nickname}")` 추가

## 테스트 규칙

자세한 테스트 가이드는 `backend_fastapi/TESTING.md` 참조.

### 테스트 실행
```bash
# 백엔드 테스트
cd backend_fastapi && pytest -v

# WebSocket 테스트만
pytest tests/test_websocket/ -v

# DB 테스트 제외 (DB 없이 실행)
pytest -v -m "not requires_db"

# 게임 엔진 테스트
pytest ../games/ -v
```

### 테스트 명명 규칙
```
test_<action>_<context>_<expected_result>
```
예: `test_move_pawn_invalid_position`, `test_join_queue_already_in_queue`

### 새 기능 추가 시
1. 기능 구현 전에 테스트 케이스 설계
2. 관련 테스트 파일에 테스트 추가
3. `pytest -v` 전체 통과 확인 후 PR

### 기존 코드 수정 시
1. 기존 테스트 먼저 실행
2. API/함수 시그니처 변경 시 테스트도 수정
3. 버그 수정 시 해당 버그를 잡는 회귀 테스트 추가

### WebSocket 테스트 패턴
```python
@pytest.mark.asyncio
async def test_handler(self, connection_manager, mock_websocket, mock_user):
    from routers.ws_game import handle_xxx

    await connection_manager.connect(mock_websocket, mock_user.id, mock_user.nickname)

    with patch("routers.ws_game.dependency", mock_dependency):
        await handle_xxx(mock_websocket, user)

    assert any(msg.get("type") == "expected_type" for msg in mock_websocket.sent_messages)
```

### DB 테스트 마커
PostgreSQL 필요한 테스트는 `@pytest.mark.requires_db` 사용:
```python
@pytest.mark.requires_db
def test_create_user(self, db_session):
    # DB 연결 없으면 자동 스킵
```
