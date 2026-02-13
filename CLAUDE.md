# CLAUDE.md

> Claude Code 전용 지침. 상세 문서는 `docs/` 참조.

---

## 프로젝트 개요

Quoridor 보드게임 플랫폼. Flutter 프론트엔드 + FastAPI 백엔드 + PostgreSQL.

**3계층 구조:**
- `games/` - 순수 Python 게임 엔진
- `backend_fastapi/` - FastAPI REST API + WebSocket
- `frontend_flutter/` - Flutter 멀티플랫폼 UI

---

## 빠른 명령어

| 작업 | 명령어 |
|------|--------|
| **Conda 활성화** | `E:/Conda/Scripts/activate && conda activate GameProject` |
| **백엔드 실행** | `cd backend_fastapi && uvicorn main:app --reload` |
| **프론트엔드 실행** | `cd frontend_flutter && flutter run -d chrome` |
| **DB 실행 (Docker)** | `docker compose up db -d` |
| **테스트 (백엔드)** | `cd backend_fastapi && pytest -v` |
| **테스트 (게임엔진)** | `pytest games/ -v` |
| **테스트 (Flutter)** | `cd frontend_flutter && flutter test` |

**상세:** [docs/setup/environment.md](docs/setup/environment.md)

---

## 문서 참조

| 주제 | 문서 |
|------|------|
| 환경 설정 | [docs/setup/environment.md](docs/setup/environment.md) |
| 테스트 가이드 | [docs/development/testing.md](docs/development/testing.md) |
| 로깅 규칙 | [docs/development/logging.md](docs/development/logging.md) |
| REST API | [docs/api/rest_api.md](docs/api/rest_api.md) |
| WebSocket | [docs/api/websocket.md](docs/api/websocket.md) |
| 전체 아키텍처 | [docs/architecture/overview.md](docs/architecture/overview.md) |

---

## 커밋 메시지 규칙

### 자동 추천 트리거
- Plan 모드 작업 완료 시
- 큰 기능 구현 완료 시
- 복잡한 버그 해결 후

### 형식
```
<Type>: <Subject>

- <변경사항 1>
- <변경사항 2>
```

**Type:** `Fix`, `Feat`, `Refactor`, `Test`, `Docs`, `Chore`

### 워크플로우
1. Claude가 코드 변경
2. Claude가 커밋 메시지 추천 (자동)
3. **사용자가 직접 코드 점검 및 수정**
4. **사용자가 직접 `git commit` 실행**

---

## DevLog 자동 생성 규칙

### 트리거 조건
- Plan 모드 작업 완료 시
- PR 생성 직전
- 복잡한 버그 해결 후
- 사용자 요청 시 ("오늘 작업 정리해줘")

### 생성 위치
`C:\Users\Administrator\Desktop\DevLogs\{YYYY-MM}\Code_Change_{YYYY-MM-DD}.md`

### DevLogs 폴더 구조
```
DevLogs/
├── Templates/
│   ├── Code_Change_Sheet.md    # 일일 변경 기록 템플릿
│   └── Blog_Template.md        # 블로그 포스팅 템플릿
├── Sources/
│   └── Project_Architecture.md # NotebookLM 소스
└── {YYYY-MM}/
    └── Code_Change_{YYYY-MM-DD}.md  # 일일 기록
```

---

## 핵심 규칙 요약

### 로깅
```python
logger.info(f"[기능명] {user.nickname} (부가정보)")
```
**상세:** [docs/development/logging.md](docs/development/logging.md)

### WebSocket 메시지
| 클라이언트 → 서버 | 서버 → 클라이언트 |
|-------------------|-------------------|
| `move`, `wall`, `surrender` | `game_state`, `game_end` |
| `join_queue`, `leave_queue` | `queue_joined`, `match_found` |
| `create_room`, `join_room` | `room_created`, `room_joined` |

**중요:** `game_state` 응답은 중첩 구조 → `message.data['game_state']` 추출 필요

**상세:** [docs/api/websocket.md](docs/api/websocket.md)

### 테스트
```bash
pytest backend_fastapi/ -v      # 백엔드
pytest games/ -v                # 게임 엔진
flutter test                    # Flutter
```

**상세:** [docs/development/testing.md](docs/development/testing.md)

---

## 좌표 참조

- **보드:** 9x9 (0-8)
- **벽:** 교차점 기준 (0-7)
- **Player 1:** 시작 (8,4), 목표 row 0
- **Player 2/AI:** 시작 (0,4), 목표 row 8
