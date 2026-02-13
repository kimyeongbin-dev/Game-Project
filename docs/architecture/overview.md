# Game Project 분석 보고서

**작성일:** 2026-02-10
**분석 대상:** E:\Project\Personal_Project\Game
**프로젝트 유형:** 멀티플랫폼 보드게임 애플리케이션 (Quoridor)

---

## 1. 프로젝트 개요

### 1.1 목적
AI 상대 또는 로컬 2인 대전이 가능한 쿼리도(Quoridor) 보드게임 애플리케이션입니다. Flutter 기반 멀티플랫폼 프론트엔드와 FastAPI 기반 백엔드로 구성됩니다.

### 1.2 기술 스택

| 계층 | 기술 |
|------|------|
| **Frontend** | Flutter 3.19+ (Dart) |
| **Backend** | FastAPI (Python 3.11+) |
| **Database** | PostgreSQL 16 (JSONB) |
| **ORM** | SQLAlchemy (비동기) |
| **컨테이너** | Docker Compose |
| **CI/CD** | GitHub Actions |
| **스케줄러** | APScheduler |

---

## 2. 아키텍처 구조

### 2.1 3계층 구조

```
┌─────────────────────────────────────────────────────────────┐
│                    Frontend (Flutter)                        │
│  - Multi-platform: Web, Windows, Android, iOS, macOS, Linux │
│  - Material 3 디자인                                         │
│  - HTTP REST API 통신                                        │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                   Backend (FastAPI)                          │
│  - REST API 서버 (포트 8000)                                 │
│  - 비즈니스 로직 (Service Layer)                             │
│  - 비동기 DB 처리                                            │
│  - Graceful Degradation (DB 없이도 동작)                     │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                  Game Engine (Pure Python)                   │
│  - 프레임워크 무관 순수 게임 로직                            │
│  - 재사용 가능한 게임 엔진                                   │
│  - 유닛 테스트 완비                                          │
└─────────────────────────────────────────────────────────────┘
```

### 2.2 디렉토리 구조

```
Game/
├── backend_fastapi/          # FastAPI 백엔드
│   ├── main.py               # 앱 진입점, 라이프사이클 관리
│   ├── routers/              # API 라우터
│   │   ├── quoridor.py       # 게임 API (/api/v1/quoridor)
│   │   ├── users.py          # 유저 API (/api/v1/users)
│   │   └── ranking.py        # 랭킹 API (/api/v1/ranking)
│   ├── services/             # 비즈니스 로직
│   │   ├── quoridor_service.py  # 게임 서비스 (싱글톤)
│   │   └── ranking_service.py   # 랭킹 서비스
│   ├── database/             # DB 계층
│   │   ├── config.py         # DB 연결 설정
│   │   ├── models.py         # SQLAlchemy 모델
│   │   └── repository.py     # 데이터 액세스
│   ├── schemas/              # Pydantic 스키마
│   ├── scheduler/            # 스케줄러
│   │   └── daily_reset.py    # 일일 리셋 작업
│   └── tests/                # 테스트 코드
│
├── frontend_flutter/         # Flutter 프론트엔드
│   └── lib/
│       ├── main.dart         # 앱 진입점
│       ├── screens/          # 화면
│       │   └── quoridor_screen.dart  # 게임 화면
│       ├── widgets/          # UI 컴포넌트
│       │   └── unified_board_widget.dart  # 게임 보드
│       ├── services/         # API 서비스
│       │   └── api_service.dart  # HTTP 클라이언트
│       └── models/           # 데이터 모델
│           └── game_state.dart
│
├── games/                    # 게임 엔진 (순수 Python)
│   └── game_Quoridor/
│       ├── core/             # 핵심 게임 로직
│       │   ├── game_state.py # 게임 상태 관리
│       │   ├── board.py      # 보드 (9x9)
│       │   ├── player.py     # 플레이어
│       │   ├── wall.py       # 벽 관리
│       │   ├── move_validator.py  # 이동 검증
│       │   └── pathfinder.py # BFS 경로 탐색
│       ├── ai/               # AI 모듈
│       │   └── simple_ai.py  # 휴리스틱 기반 AI
│       └── serializers/      # 직렬화
│
├── docs/                     # 문서
├── .github/workflows/        # CI/CD 워크플로우
└── docker-compose.yml        # Docker 설정
```

---

## 3. 게임 기능

### 3.1 쿼리도(Quoridor) 규칙

- **보드:** 9x9 격자 (좌표 0-8)
- **목표:** 반대편 끝에 먼저 도달
- **벽:** 각 플레이어 10개, 2칸 길이, 교차점에 배치 (0-7 범위)
- **플레이어 시작 위치:**
  - Player 1: (8, 4) → 목표 row 0
  - Player 2/AI: (0, 4) → 목표 row 8

### 3.2 게임 모드

| 모드 | 설명 |
|------|------|
| **vs_ai** | AI 대전 (Easy/Normal/Hard) |
| **local_2p** | 로컬 2인 대전 |
| **online_2p** | 온라인 2인 대전 (구현 준비 중) |

### 3.3 AI 시스템

**휴리스틱 기반 AI (`simple_ai.py`)**

| 난이도 | 벽 설치 확률 | 랜덤 행동 확률 |
|--------|-------------|---------------|
| Easy | 10% | 30% |
| Normal | 25% | 15% |
| Hard | 40% | 5% |

**AI 전략:**
1. 승리 직전이면 무조건 이동
2. 상대가 더 가까우면 벽으로 방해
3. BFS로 최단 경로 계산
4. 벽 효과 평가 (상대 경로 증가량)

### 3.4 리플레이 시스템

- 모든 수를 `GameMove` 테이블에 저장
- 스텝별 게임 상태 스냅샷 저장
- 처음/이전/다음/마지막 탐색 지원
- 게임 종료 후 리플레이 가능

---

## 4. UI 구조

### 4.1 화면 구성

```
┌─────────────────────────────────────────┐
│              HomeScreen                  │
│  - 게임 선택 메뉴                        │
│  - 쿼리도 / 오목(준비중)                 │
└─────────────────────────────────────────┘
                  │
                  ▼
┌─────────────────────────────────────────┐
│           QuoridorScreen                 │
│  ┌─────────────────────────────────┐    │
│  │         GameInfoCard             │    │
│  │  (플레이어 정보, 벽 개수, 턴)    │    │
│  └─────────────────────────────────┘    │
│  ┌─────────────────────────────────┐    │
│  │       UnifiedBoardWidget         │    │
│  │  (17x17 통합 보드)               │    │
│  │  - 셀 (9x9)                      │    │
│  │  - 벽 슬롯 (8x8 수평/수직)       │    │
│  │  - 교차점 (8x8)                  │    │
│  └─────────────────────────────────┘    │
│  ┌─────────────────────────────────┐    │
│  │         Control Panel            │    │
│  │  - 이동/벽 모드 전환             │    │
│  │  - 수평/수직 벽 선택             │    │
│  └─────────────────────────────────┘    │
└─────────────────────────────────────────┘
```

### 4.2 UI 기능

| 기능 | 설명 |
|------|------|
| **이동 모드** | 유효한 셀 하이라이트, 탭으로 이동 |
| **벽 모드** | 벽 설치 가능 위치 표시, 방향 선택 |
| **턴 회전** | 현재 플레이어 방향으로 보드 180° 회전 (토글 가능) |
| **리플레이** | 게임 복기 기능 (처음/이전/다음/마지막) |
| **게임 복구** | 서버 재시작 후 세션 복구 |
| **다크 모드** | Material 3 다크 테마 지원 |

---

## 5. API 구조

### 5.1 엔드포인트 목록

#### 게임 API (`/api/v1/quoridor`)

| Method | Endpoint | 설명 |
|--------|----------|------|
| GET | `/sessions` | 진행 중인 게임 목록 |
| POST | `/games` | 새 게임 생성 |
| GET | `/games/{id}` | 게임 상태 조회 |
| POST | `/games/{id}/move` | 폰 이동 |
| POST | `/games/{id}/wall` | 벽 설치 |
| POST | `/games/{id}/ai-move` | AI 턴 실행 |
| GET | `/games/{id}/valid-moves` | 유효한 이동 목록 |
| POST | `/games/{id}/recover` | DB에서 게임 복구 |
| POST | `/games/{id}/abandon` | 게임 포기 |
| DELETE | `/games/{id}` | 게임 삭제 |
| GET | `/games/{id}/replay/moves` | 리플레이 수 목록 |
| GET | `/games/{id}/replay/state/{step}` | 특정 스텝 상태 |

#### 유저 API (`/api/v1/users`)

| Method | Endpoint | 설명 |
|--------|----------|------|
| POST | `/register` | 회원 가입 |
| POST | `/login` | 로그인 |
| GET | `/me` | 내 정보 조회 |
| POST | `/heartbeat` | 접속 유지 |
| POST | `/logout` | 로그아웃 |
| GET | `/check-nickname/{nickname}` | 닉네임 중복 확인 |

#### 랭킹 API (`/api/v1/ranking`)

| Method | Endpoint | 설명 |
|--------|----------|------|
| GET | `/leaderboard` | 리더보드 조회 |
| GET | `/my-rank` | 내 순위 조회 |
| GET | `/champion` | 전날 챔피언 조회 |
| GET | `/champions` | 최근 N일 챔피언 목록 |

---

## 6. 데이터베이스 설계

### 6.1 주요 테이블

```
┌────────────────────┐
│       users        │
├────────────────────┤
│ id (PK)            │
│ nickname (UNIQUE)  │
│ password_hash      │
│ session_token      │
│ score, wins, losses│
│ best_turn_count    │
│ is_online          │
│ current_game_id    │
└────────────────────┘

┌────────────────────┐
│   game_sessions    │
├────────────────────┤
│ game_id (PK, UUID) │
│ status (enum)      │
│ game_mode (enum)   │
│ player1/2_name     │
│ current_turn       │
│ turn_count         │
│ ai_difficulty      │
│ game_state (JSONB) │
│ game_history(JSONB)│
│ is_deleted         │
└────────────────────┘

┌────────────────────┐
│    game_moves      │
├────────────────────┤
│ id (PK)            │
│ game_id (FK)       │
│ step_no            │
│ player             │
│ action_type        │
│ row, col           │
│ orientation        │
│ game_state_snapshot│
└────────────────────┘

┌────────────────────┐
│  daily_champions   │
├────────────────────┤
│ id (PK)            │
│ nickname           │
│ score, wins, losses│
│ champion_date      │
│ preserved_user_id  │
└────────────────────┘
```

### 6.2 데이터베이스 특징

- **JSONB 저장:** 게임 상태를 JSONB로 저장하여 유연성 확보
- **Graceful Degradation:** DB 연결 실패 시 메모리 모드로 동작
- **비동기 처리:** asyncpg + SQLAlchemy async
- **소프트 삭제:** `is_deleted` 플래그로 기록 보존

---

## 7. 환경 설정

### 7.1 Docker Compose 구성

```yaml
services:
  db:        # PostgreSQL 16 Alpine
  backend:   # FastAPI 서버
```

### 7.2 환경 변수

| 변수 | 기본값 | 설명 |
|------|--------|------|
| `DATABASE_URL` | `postgresql+asyncpg://...` | DB 연결 문자열 |
| `DB_ENABLED` | `true` | DB 활성화 여부 |
| `PYTHONPATH` | `/workspace` | games 패키지 접근용 |

### 7.3 CI/CD (GitHub Actions)

**워크플로우:** `test-and-merge.yml`

```
dev-test (push)
    ├── backend-tests (pytest + PostgreSQL)
    ├── frontend-tests (flutter analyze/test)
    └── game-engine-tests (pytest)
          │
          ▼ (모두 성공 시)
      auto-merge → develop
```

---

## 8. 보안 분석

### 8.1 현재 구현된 보안 기능

| 기능 | 구현 상태 | 설명 |
|------|----------|------|
| **비밀번호 해시** | O | bcrypt 사용 (password_hash) |
| **세션 토큰** | O | 64자리 랜덤 토큰 발급 |
| **Bearer 인증** | O | Authorization 헤더 검증 |
| **닉네임 유효성** | O | 2-20자, 영문/숫자/한글/언더스코어 |
| **CORS 설정** | O | 개발 환경용 전체 허용 |

### 8.2 보안 취약점 및 권고사항

#### 8.2.1 Critical (즉시 수정 필요)

| 취약점 | 위치 | 설명 | 권고사항 |
|--------|------|------|----------|
| **CORS 전체 허용** | `main.py:59-64` | `allow_origins=["*"]` 설정 | 프로덕션에서는 특정 도메인만 허용 |
| **DB 비밀번호 노출** | `config.py:18` | 기본 비밀번호가 코드에 하드코딩 | 환경 변수로 분리, `.env` 파일 사용 |
| **세션 토큰 유효기간 없음** | `users.py` | 토큰 만료 시간 미설정 | JWT 또는 만료 시간 추가 |

#### 8.2.2 High (우선 수정 권장)

| 취약점 | 위치 | 설명 | 권고사항 |
|--------|------|------|----------|
| **Rate Limiting 없음** | 전체 API | API 호출 제한 미구현 | slowapi 등으로 Rate Limit 추가 |
| **인증 없는 게임 API** | `quoridor.py` | 게임 생성/조작에 인증 불필요 | 랭킹전 시 유저 인증 연동 |
| **SQL Injection** | 낮음 | SQLAlchemy ORM 사용으로 대부분 방지 | 직접 쿼리 작성 시 파라미터 바인딩 확인 |

#### 8.2.3 Medium (개선 권장)

| 취약점 | 설명 | 권고사항 |
|--------|------|----------|
| **로깅 민감정보** | 디버그 로그에 민감 정보 포함 가능 | 프로덕션 로그 레벨 조정 |
| **에러 메시지 노출** | 상세 에러 메시지가 클라이언트에 노출 | 프로덕션에서 일반적 에러 메시지 반환 |
| **HTTPS 미적용** | HTTP 통신 사용 | 프로덕션에서 HTTPS 필수 |

---

## 9. 서비스 구조

### 9.1 싱글톤 서비스

```python
# quoridor_service.py
class QuoridorService:
    CACHE_TTL_MINUTES = 60
    MAX_CACHED_GAMES = 100

    _games: dict[str, GameState] = {}  # 메모리 캐시
    _ai_instances: dict[str, SimpleAI] = {}  # AI 인스턴스
    _last_accessed: dict[str, datetime] = {}  # LRU 추적

quoridor_service = QuoridorService()  # 싱글톤
```

### 9.2 캐시 전략

- **Write-Through:** 메모리 + DB 동시 저장
- **LRU Eviction:** 최대 100개 게임, 60분 TTL
- **Lazy Loading:** DB에서 필요 시 로드

### 9.3 스케줄러

**일일 리셋 (KST 09:00 / UTC 00:00)**
1. 현재 1위 유저를 `daily_champions` 테이블에 저장
2. 게임 중이 아닌 유저 전체 삭제
3. 1위 유저만 유지 (점수 리셋)

---

## 10. 배포 환경

### 10.1 현재 구성

| 환경 | 설명 |
|------|------|
| **개발** | 로컬 Docker Compose (PostgreSQL + FastAPI) |
| **테스트** | GitHub Actions (pytest + Flutter analyze) |
| **스테이징** | 미구성 |
| **프로덕션** | 미구성 |

### 10.2 Docker 이미지

```dockerfile
# backend_fastapi/Dockerfile
FROM python:3.11-slim
WORKDIR /workspace/backend_fastapi
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
```

### 10.3 권장 프로덕션 구성

```
┌─────────────────────────────────────────────────────────────┐
│                        Load Balancer                         │
│                    (Nginx / AWS ALB)                         │
└─────────────────────────────────────────────────────────────┘
                              │
        ┌─────────────────────┼─────────────────────┐
        ▼                     ▼                     ▼
┌───────────────┐   ┌───────────────┐   ┌───────────────┐
│   Backend 1   │   │   Backend 2   │   │   Backend N   │
│   (FastAPI)   │   │   (FastAPI)   │   │   (FastAPI)   │
└───────────────┘   └───────────────┘   └───────────────┘
        │                     │                     │
        └─────────────────────┼─────────────────────┘
                              ▼
                    ┌───────────────┐
                    │  PostgreSQL   │
                    │  (Primary)    │
                    └───────────────┘
```

---

## 11. 개선점 및 권고사항

### 11.1 즉시 개선 필요

| 우선순위 | 항목 | 설명 |
|----------|------|------|
| 1 | **CORS 설정** | 프로덕션 도메인만 허용하도록 수정 |
| 2 | **환경 변수 분리** | DB 비밀번호 등 민감 정보를 `.env`로 분리 |
| 3 | **세션 만료** | 토큰 유효기간 설정 (예: 24시간) |
| 4 | **Rate Limiting** | API 호출 제한 추가 |

### 11.2 기능 개선

| 항목 | 현재 상태 | 권고사항 |
|------|----------|----------|
| **온라인 2P 대전** | 모델만 정의됨 | WebSocket 기반 실시간 대전 구현 |
| **매칭 시스템** | `MatchQueue` 테이블 존재 | 자동 매칭 로직 구현 |
| **방 시스템** | `GameRoom` 테이블 존재 | 방 코드 기반 초대 구현 |
| **랭킹전 연동** | `is_ranked` 필드 존재 | 게임 결과 → 점수 반영 로직 |
| **Flutter 테스트** | 없음 | Widget/Integration 테스트 추가 |

### 11.3 아키텍처 개선

| 항목 | 권고사항 |
|------|----------|
| **Redis 캐시** | 메모리 캐시 대신 Redis 사용 (다중 인스턴스 지원) |
| **WebSocket** | 실시간 게임 업데이트용 WebSocket 추가 |
| **이벤트 소싱** | 게임 이벤트 기반 상태 관리 고려 |
| **마이크로서비스** | 게임/유저/랭킹 서비스 분리 고려 |

### 11.4 인프라 개선

| 항목 | 권고사항 |
|------|----------|
| **HTTPS** | Let's Encrypt 또는 AWS ACM 적용 |
| **컨테이너 오케스트레이션** | Kubernetes 또는 AWS ECS 도입 |
| **모니터링** | Prometheus + Grafana 또는 AWS CloudWatch |
| **로깅** | ELK Stack 또는 AWS CloudWatch Logs |
| **백업** | PostgreSQL 자동 백업 설정 |

---

## 12. 테스트 현황

### 12.1 테스트 커버리지

| 영역 | 테스트 파일 | 상태 |
|------|------------|------|
| **Game Engine** | `games/tests/test_*.py` | 완비 |
| **Backend API** | `backend_fastapi/tests/test_*.py` | 완비 |
| **Frontend** | 없음 | 미구현 |

### 12.2 테스트 목록

**Game Engine:**
- `test_board.py` - 보드 초기화
- `test_player.py` - 플레이어 이동
- `test_wall.py` - 벽 배치
- `test_pathfinder.py` - BFS 경로 탐색
- `test_move_validator.py` - 이동 유효성 검증
- `test_game_state.py` - 게임 상태 관리
- `test_ai.py` - AI 동작
- `test_scenarios.py` - 시나리오 테스트

**Backend:**
- `test_api.py` - API 엔드포인트
- `test_service.py` - 서비스 레이어
- `test_repository.py` - DB 액세스
- `test_replay.py` - 리플레이 기능
- `test_users.py` - 유저 기능
- `test_ranking.py` - 랭킹 기능
- `test_health.py` - 헬스 체크

---

## 13. 결론

### 13.1 프로젝트 성숙도

| 영역 | 성숙도 | 설명 |
|------|--------|------|
| **게임 로직** | 높음 | 완전한 쿼리도 규칙 구현, AI 완비 |
| **백엔드 API** | 높음 | REST API 완성, 리플레이/랭킹 기능 |
| **프론트엔드** | 중간 | 기본 UI 완성, 테스트 부족 |
| **보안** | 낮음 | 기본 인증만 구현, 보완 필요 |
| **인프라** | 낮음 | 개발 환경만 구성, 프로덕션 미준비 |

### 13.2 다음 단계 권장 사항

1. **보안 강화** - CORS, Rate Limiting, HTTPS 적용
2. **프론트엔드 테스트** - Widget/Integration 테스트 추가
3. **온라인 대전** - WebSocket 기반 실시간 게임 구현
4. **프로덕션 배포** - 클라우드 인프라 구성

---

*이 보고서는 Claude Code에 의해 자동 생성되었습니다.*
