# Backend Testing Guide

백엔드 테스트 작성 및 유지보수 가이드입니다.

## 테스트 실행

### 전체 테스트 실행
```bash
# Conda 환경 활성화 필요
E:/Conda/Scripts/activate && conda activate GameProject
cd backend_fastapi && pytest -v
```

### 특정 테스트만 실행
```bash
# WebSocket 테스트
pytest tests/test_websocket/ -v

# API 테스트
pytest tests/test_api.py -v

# DB 테스트 (DB 연결 필요)
pytest tests/test_repository.py -v

# 게임 엔진 테스트
pytest ../games/ -v
```

### 테스트 커버리지
```bash
pytest --cov=. --cov-report=html
```

---

## 테스트 구조

```
backend_fastapi/tests/
├── conftest.py                  # 공통 fixture, 환경 설정
├── test_api.py                  # REST API 테스트 (26개)
├── test_repository.py           # DB Repository 테스트 (41개)
├── test_service.py              # Service 테스트
├── test_health.py               # Health check 테스트
└── test_websocket/              # WebSocket 테스트 (64개)
    ├── conftest.py              # WebSocket 전용 fixture
    ├── test_connection_manager.py
    ├── test_matchmaking.py
    ├── test_room_manager.py
    └── test_ws_handlers.py
```

---

## Fixture 사용법

### 공통 Fixture (`conftest.py`)

| Fixture | 설명 | 사용 예 |
|---------|------|--------|
| `client` | FastAPI TestClient (인증 모킹 포함) | API 테스트 |
| `mock_get_current_user` | 인증된 사용자 모킹 | 인증 필요 API |
| `sample_game_data` | 샘플 게임 데이터 | 게임 관련 테스트 |
| `sample_wall_data` | 샘플 벽 데이터 | 벽 설치 테스트 |

### WebSocket Fixture (`test_websocket/conftest.py`)

| Fixture | 설명 | 비동기 |
|---------|------|-------|
| `mock_websocket` | Mock WebSocket 객체 | No |
| `mock_user` | 테스트용 사용자 1 | No |
| `mock_user2` | 테스트용 사용자 2 | No |
| `connection_manager` | ConnectionManager 인스턴스 | Yes |
| `matchmaking_queue` | MatchmakingQueue (started) | Yes |
| `matchmaking_queue_stopped` | MatchmakingQueue (not started) | Yes |
| `room_manager` | RoomManager 인스턴스 | No |

---

## 테스트 마커

### `@pytest.mark.requires_db`
PostgreSQL DB 연결이 필요한 테스트에 사용합니다.
DB 없이 실행 시 자동으로 스킵됩니다.

```python
@pytest.mark.requires_db
def test_create_user(db_session):
    # DB 테스트 코드
```

### `@pytest.mark.asyncio`
비동기 테스트에 사용합니다. (`pytest-asyncio` 설치 필요)

```python
@pytest.mark.asyncio
async def test_async_function():
    result = await some_async_function()
    assert result is not None
```

---

## 테스트 작성 가이드

### 명명 규칙
```
test_<action>_<context>_<expected_result>
```

예시:
- `test_create_game_success`
- `test_move_pawn_invalid_position`
- `test_join_queue_already_in_queue`

### 테스트 클래스 구조
```python
class TestFeatureName:
    """기능 설명"""

    def test_success_case(self, fixture):
        """정상 케이스"""
        # Given
        # When
        # Then

    def test_error_case(self, fixture):
        """에러 케이스"""
        # Given
        # When / Then
        with pytest.raises(ValueError):
            ...
```

### API 테스트 패턴
```python
def test_create_game(self, client, sample_game_data):
    """게임 생성 API 테스트"""
    response = client.post("/api/v1/quoridor/games", json=sample_game_data)

    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert "game_id" in data
```

### WebSocket 테스트 패턴
```python
@pytest.mark.asyncio
async def test_join_queue(self, connection_manager, matchmaking_queue, mock_websocket, mock_user):
    """큐 참가 테스트"""
    from routers.ws_game import handle_join_queue

    # 연결
    await connection_manager.connect(mock_websocket, mock_user.id, mock_user.nickname)

    # 핸들러 실행 (의존성 모킹)
    with patch("routers.ws_game.matchmaking_queue", matchmaking_queue):
        await handle_join_queue(mock_websocket, user)

    # 결과 확인
    assert any(msg.get("type") == "queue_joined" for msg in mock_websocket.sent_messages)
```

### Repository 테스트 패턴
```python
@pytest.mark.requires_db
@pytest.mark.asyncio
async def test_create_user(self, db_session):
    """유저 생성 테스트"""
    repo = UserRepository(db_session)

    user = await repo.create(nickname="TestUser", password="hashed")

    assert user.id is not None
    assert user.nickname == "TestUser"
```

---

## 모킹 가이드

### AsyncMock 사용
```python
from unittest.mock import AsyncMock, patch

mock_service = AsyncMock()
mock_service.get_game.return_value = mock_game

with patch("routers.quoridor.quoridor_service", mock_service):
    response = client.get(f"/api/v1/quoridor/games/{game_id}")
```

### 의존성 모킹
```python
# conftest.py에서 설정
from unittest.mock import patch, MagicMock

def mock_get_current_user():
    async def _mock():
        return MockUser()
    return _mock

@pytest.fixture
def client(mock_get_current_user):
    with patch("routers.users.get_current_user", mock_get_current_user()):
        yield TestClient(app)
```

---

## 코드 수정 시 테스트 업데이트

### API 변경 시
1. 엔드포인트 URL 변경 → `test_api.py` 수정
2. 요청/응답 스키마 변경 → `sample_*_data` fixture 수정
3. 인증 방식 변경 → `mock_get_current_user` 수정

### WebSocket 메시지 변경 시
1. 메시지 타입 변경 → 해당 핸들러 테스트 수정
2. 응답 필드 변경 → assert 문 수정
3. 새 핸들러 추가 → `test_ws_handlers.py`에 테스트 추가

### DB 스키마 변경 시
1. 모델 필드 변경 → Repository 테스트 수정
2. 새 모델 추가 → 새 테스트 클래스 추가

---

## CI/CD 통합

### GitHub Actions
`.github/workflows/test-and-merge.yml`에서 자동 테스트 실행

```yaml
- name: Run tests
  run: |
    cd backend_fastapi
    pytest -v --tb=short
```

### DB 테스트 in CI
CI 환경에서는 PostgreSQL이 제공되므로 `@pytest.mark.requires_db` 테스트도 실행됩니다.

로컬에서 DB 없이 테스트 시:
```bash
# DB 테스트 제외
pytest -v -m "not requires_db"
```

---

## 트러블슈팅

### Rate Limit 에러
테스트 환경에서는 자동으로 비활성화됩니다.
```python
# conftest.py
os.environ["TESTING"] = "true"
```

### DB 연결 실패
`@pytest.mark.requires_db` 마커가 있는 테스트는 자동 스킵됩니다.

### 비동기 테스트 실패
`pytest-asyncio` 설치 확인:
```bash
pip install pytest-asyncio
```

`pyproject.toml` 설정 확인:
```toml
[tool.pytest.ini_options]
asyncio_mode = "auto"
```

---

## 체크리스트

### 새 기능 추가 시
- [ ] 단위 테스트 작성
- [ ] 통합 테스트 작성 (필요 시)
- [ ] 에러 케이스 테스트
- [ ] `pytest -v` 전체 통과 확인

### 기존 코드 수정 시
- [ ] 기존 테스트 실행
- [ ] 실패 테스트 수정
- [ ] 회귀 테스트 추가 (버그 수정 시)

### PR 전 체크
- [ ] 로컬 테스트 통과
- [ ] CI 테스트 통과
- [ ] 커버리지 확인
