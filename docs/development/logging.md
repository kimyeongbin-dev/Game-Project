# 로깅 가이드

> INFO 레벨 로그 작성 규칙

---

## 로그 레벨

| 레벨 | 용도 | 환경 |
|------|------|------|
| `DEBUG` | 모든 로그 (SQL 쿼리 포함) | 디버깅 |
| `INFO` | 핵심 비즈니스 로직만 | 개발 (기본값) |
| `WARNING` | 경고/에러만 | 배포 |

**설정 방법 (.env):**
```bash
LOG_LEVEL=INFO
```

---

## 필수 로깅 대상

새로운 기능을 구현할 때 반드시 INFO 레벨 로그를 추가해야 합니다.

| 분류 | 이벤트 |
|------|--------|
| **사용자 인증** | 회원가입, 로그인, 로그아웃 |
| **게임 이벤트** | 게임 생성, 시작, 종료, 포기 |
| **매칭 시스템** | 대기열 참가/나가기, 매칭 완료 |
| **게임 액션** | 말 이동, 벽 설치, 항복 |
| **방 관리** | 방 생성, 참가, 나가기, 준비 완료 |

---

## 로그 형식

```python
import logging
logger = logging.getLogger(__name__)

# 형식: [기능명] 주요정보 (부가정보)
logger.info(f"[회원가입] {user.nickname}")
logger.info(f"[게임 생성] {user.nickname} (모드: {game_mode}, 게임: {game_id[:8]})")
logger.info(f"[말 이동] {user.nickname} -> ({row}, {col}) (게임: {game_id[:8]})")
logger.info(f"[대기열 참가] {user.nickname} (위치: {position})")
```

---

## 주의사항

- `game_id`는 처음 8자리만 표시: `game_id[:8]`
- SQLAlchemy 및 연결 로그는 INFO에서 표시하지 않음
- WebSocket 연결/해제는 이미 로깅됨

---

## 파일별 로깅 현황

| 파일 | 로깅 대상 |
|------|----------|
| `routers/users.py` | 회원가입, 로그인 |
| `routers/ws_game.py` | 대기열, 방 관리, 게임 액션 |
| `routers/quoridor.py` | 게임 생성, 포기 |
