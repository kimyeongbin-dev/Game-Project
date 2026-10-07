# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

**응답 언어: 한국어.** 사용자에게 보이는 모든 텍스트(진행 보고·질문·최종 요약)는 한국어로 쓴다. 코드 식별자·명령어·커밋 해시는 그대로 둔다. 커밋 메시지·저장소 문서도 한국어다.

**이 파일은 매 세션 지켜야 할 규칙·불변식과 포인터만 둔다(공식 권장 200줄 이내).** 절차·명령·배경은 링크한 문서에 있다 — 여기에 다시 풀어 쓰지 않는다.

## 프로젝트

**게임모아 (gamemoa)** — 크로스플랫폼 통합 미니게임 플랫폼. 벤토 그리드 로비에서 6종 보드·퍼즐 게임에 접속한다.
**단일 기준 문서(SSOT): [`PLATFORM_ARCHITECTURE.md`](PLATFORM_ARCHITECTURE.md)** — 스택·보안 원칙·게임별 명세·디렉토리 청사진. 구조·스택 판단은 이 문서를 우선한다.

- **솔로 플레이**: 비로그인 / 100% 오프라인. 판정·로컬 AI·세이브가 전부 클라이언트 안
- **멀티플레이**: 카카오 로그인 필수 / 온라인. 승패·전적·MMR 은 **반드시 서버가 판정**, 클라이언트 주장은 신뢰하지 않는다(Zero-Trust, §3.3 원칙 2)

### 작업 재개 — 무엇을 언제 읽나 (통째로 읽지 말 것)

| 시점 | 읽을 것 | 목적 |
| :-- | :-- | :-- |
| 세션 시작 | 이 파일 + 메모리 인덱스(자동) → [`docs/ROADMAP.md`](docs/ROADMAP.md) 맨 위 "현재 위치" 문단과 진행 중인 마일스톤 절만 | 다음 할 일 |
| 계획 수립 | [`docs/plans/README.md`](docs/plans/README.md) "검증 관문과 독립 검토"·"모델 분할 표시" → **직전 계획서의 상태 머리글**(계획 이탈·계획 오류 = 반복하지 말 것) | 규약·교훈 |
| 이관 항목을 다룰 때 | ROADMAP 항목이 가리키는 `docs/research/*독립검토*.md` 의 **채택표 해당 행만**, 필요하면 그 원문 항목 | 지적의 원래 근거 |
| 동작·수치를 인용할 때 | `docs/research/*실측*.md` 의 "알려진 한계"·해당 시나리오 절 | 실측 근거(추정 금지) |
| 와이어·키·규칙 | `docs/api/games/maze.md`·`docs/api/platform.md` 의 해당 절(§ 번호로) | 설계 정본 |
| 명령·환경·버전 절차 | [`docs/환경.md`](docs/환경.md) 해당 절 | 실행 방법 |

계획서 본문·검토 원문 전체·결과 원자료(`server/harness/multiworker/results/`, git 밖)는 근거를 확인할 때만 연다.

## 개발 환경 — 모든 것이 Docker

로컬에 Python/Postgres/Redis 를 설치하지 않는다. `.env.example` → `.env` 복사 후:

```bash
docker compose up -d                                        # db + redis + server(hot reload) + proxy(Caddy)
docker compose run --rm server-test                         # 서버 전체 테스트(전용 gamemoa_test DB·Redis DB 1)
docker compose run --rm server-test pytest tests/games -q   # 일부만
docker compose run --rm client-test                         # Flutter analyze + test
curl -s http://localhost:8000/health | python -m json.tool  # 호스트 :8000 = Caddy → server
```

- 컨테이너에서 불가능한 것(USB·GUI)만 로컬 Flutter: `flutter run -d <device>`, `dart run build_runner build`
- 웹·Android 빌드, 운영 이미지 로컬 검증, API Base URL(에뮬레이터 `10.0.2.2:8000`): [`docs/환경.md`](docs/환경.md)
- **호스트 :8000 은 Caddy 다. server 는 호스트 포트를 열지 않는다.** 네트워크는 고정 서브넷 `10.231.0.0/24`·proxy `.10`(겹치면 `.env` 로 변경) — [`docs/환경.md`](docs/환경.md) "리버스 프록시·네트워크"
- 프록시 경유 E2E: `bash scripts/e2e-proxy.sh`(운영 이미지·설정, CI 와 같음) → 개발 복귀는 **반드시** `docker compose up -d --build`

## 버전 고정 — 자동 변경은 절대 없다

모든 버전이 고정돼 있고 `scripts/check-version-pinning.sh` 가 검사한다(CI `version-guard`). 대상·절차 표는 [`docs/환경.md`](docs/환경.md) "버전 고정".

- 서버 의존성은 `pyproject.toml` `==` + `uv.lock`(해시), 이미지는 `name:tag@sha256:`, Actions 는 40자 SHA, Flutter 는 `.flutter-version` 단일 기준
- **`flutter pub upgrade` 금지**(숫자를 직접 바꾼다), **`pubspec.yaml` 의 `sdk:` 제약을 낮춰 낡은 툴체인을 통과시키지 않는다**
- 의존성(이미지·패키지·액션·플러그인) 추가는 **사용자 사전 승인** 후

## 아키텍처

```
client/   Flutter — Android → iOS → Web        server/   FastAPI (Python 3.13+)        infra/   caddy·postgres 초기화
```

- **client/lib**: `hub/`·`games/` → `core/` 단방향. `core/` 는 게임을 참조하지 않고, 게임끼리 직접 참조 금지. 무거운 연산(로컬 AI·역산 보드·이미지 분할)은 **반드시 Dart Isolate**. 디렉토리마다 책임을 적은 `README.md` — 새 코드 전에 읽는다
- **server/app**: `main.py`(엔트리·lifespan) · `core/`(설정·토큰 검증·로그 마스킹·시계·워커 id·오리진) · `db/`(SQLAlchemy async·Redis 연결) · `api/`(REST) · `ws/`(핸들러·와이어·런타임·리밋·버스) · `schemas/` · `services/`(서버 권위 로직) · `games/maze/`(순수 판정 엔진)
- import 는 항상 `app.` 절대 경로(`sys.path` 조작 금지). 테스트는 `server/tests/` 에 소스 구조 그대로

### 불변식 — 바꿀 때 멈추고 확인

- **Graceful degradation**: DB·Redis 연결 실패로 기동이 막히지 않는다. DB 전 `is_db_available()`, Redis 전 `is_redis_available()`. 단 **멀티플레이는 Redis 없이 성립하지 않는다**
- **멀티플레이 상태는 Redis 에만**(`services/maze_game.py`·`matchmaking.py`·`rooms.py`·`activity.py`). 서비스 인스턴스는 상태가 없다. state·시야·시계·데드라인은 **같은 락 토큰의 펜싱 쓰기 한 번**(`fenced_write`), 시각은 Redis `TIME`
- **게임 이벤트 발행은 그 펜싱 쓰기와 같은 Lua 안의 `PUBLISH`**(`RedisPublisher.in_commit`) — 이벤트는 권위 없음·at-most-once, 워커마다 `ws/bus.py` 가 구독해 자기 소켓에만 보낸다. 쓰기와 발행을 다시 떼지 말 것(사이에 워커가 죽으면 통지가 영영 사라졌다, M4-1)
- **새 Redis 클라이언트는 `connection_class=PinnedConnection`**(`app/db/redis.py` — 해석해 둔 주소로 접속. Redis 가 꺼진 동안의 느린 이름 조회가 재접속을 막았다, M4-1)
- **키는 `app/db/redis_keys.py` 에서만**(스키마 표: `docs/api/platform.md` "Redis 키 스키마"). Redis 논리 DB: **0 = 앱, 1 = 테스트, 2 = 리미터**. Pub/Sub 은 DB 로 격리되지 않아 `PUBSUB_NAMESPACE`(`app`/`test`)로 나눈다 — production 은 `test` 로 기동하지 않는다
- **환경변수는 `app/core/config.py` 에서만** 읽는다(`os.getenv` 금지). 유일한 예외: uvicorn 이 직접 읽는 `FORWARDED_ALLOW_IPS`
- **좌석 소유 = 연결 id**(`<worker_id>:<토큰>`). 끊김은 그 유저의 현재 연결일 때만 기록된다(락 안에서 `user:{uid}:conn` 대조)
- **소켓에 보내지 않는 것**: `ActionOutcome.state`(전체 상태), 예외 문구(§13 코드·고정 문구만), 이벤트 hint 의 금지 키
- **개수를 박지 않는다**: 인원·게임·모드 수 고정값 금지 — "인원이 4명이 되면 무엇을 고치나?"(`docs/api/platform.md` §5)
- **하드웨어 금고 키**: AES/HMAC 키를 소스에 두지 않는다 — 기기에서 생성해 Keystore/Keychain 에만(§3.2)
- 게임 상태 직렬화: `GameState.to_dict()`/`from_dict()` 가 `game:<id>:state` 전체, `schema_version` 이 다르면 복원 거부

### 프록시·리밋

- **신뢰 경계**: Caddy 는 `CADDY_TRUSTED_PROXIES`(엣지)만 믿고 **strict**(오른쪽부터)로 판정한 `{client_ip}` 하나로 XFF 를 다시 쓴다. uvicorn 은 `FORWARDED_ALLOW_IPS` = proxy 주소만 믿는다. **`--forwarded-allow-ips *`·모두 신뢰 금지**, Caddy 사이트 `log` 금지(전역 로거가 `?token=` 을 지운다) — `scripts/check-proxy-config.sh`·CI 가 막는다
- 오리진: `CORS_ALLOWED_ORIGINS`(운영 기본 = 없음, `*` 면 기동 거부), WS 도 같은 목록(`app/core/origins.py`)
- REST 리미터 핸들러는 **반드시 동기 `def`**(`async def` 면 slowapi 가 커스텀 429 를 조용히 버린다 — `tests/api/test_rate_limit.py`). 저장소가 메모리로 강등되면 워커 수만큼 한도가 곱해진다
- WS IP 리밋은 **접속 실패만** 센다(유효 토큰은 계정 리밋) — NAT 공유자 보호

## 진행 상태 (인프라 M4-1 완료, 다음 M4-2)

| 영역 | 상태 |
| :-- | :-- |
| 미로 엔진 `games/maze/` | N인 좌석 일반화(M3 1)·시야 엔진(M3 5) 완료. 도메인 리네이밍 미적용 |
| 큐·방·게임 상태·DB | Redis 이전(M3 3)·2인 전제 제거(M3 2). 마이그레이션은 `create_all` — Alembic 은 첫 운영 배포 전 |
| 실시간 `ws/`·시간 체계 | 완료(M3 6·7) — 다중 워커 완료 판정, prod `--workers 2` |
| 리버스 프록시·리밋·오리진 | 완료(M4-1) |
| 인증(카카오 OIDC·토큰 발급)·MMR | 미착수 — 지금은 access token **검증만**, MMR 초기값 임시 |
| `client/lib/**` | 골격 + 허브 placeholder |
| 나머지 5종 게임 | 미착수 |

세부·남은 작업·TODO: [`docs/ROADMAP.md`](docs/ROADMAP.md). API 계약: [`docs/api/platform.md`](docs/api/platform.md), [`docs/api/games/maze.md`](docs/api/games/maze.md).
**구조 변경·대규모 코드 전에는 플랜 모드로 계획부터.** 계획서는 `docs/plans/`(규약: [`docs/plans/README.md`](docs/plans/README.md) — 커밋별 검증 관문 G1~G5, 반증 `python scripts/falsify.py`, 마지막 독립 검토, 완료 후 이름·상태 머리글).

## 브랜치·레거시

- 지금은 `feature/platform-restructure` 에서 작업·push 한다
- `backend_fastapi/`·`frontend_flutter/`·`games/` 는 영구 폐기 — 되살리지 않는다. `origin/develop`·`origin/dev-test` 는 그 경로를 가진 히스토리라 **머지하지 말고** 내용만 꺼낸다(`git show origin/develop:<구 경로>`). 3중 차단(ancestry·pre-commit·CI) 상세와 훅 활성화(`git config core.hooksPath .githooks`)는 [`docs/환경.md`](docs/환경.md) 끝

## 주의사항

- **다중 워커 동작을 바꾸면 하네스 `server/harness/multiworker/`(실제 워커 2개 + Redis 장애 + 프록시)를 다시 돌린다** — pytest 는 한 프로세스라 워커 간 경합·신호·실제 장애를 재현하지 못한다. 실행 비용·중단 조건을 계획서에 먼저
- `docs/quoridor/` 는 재설계 대기 중인 **구 API 문서** — 새 작업의 근거로 삼지 않는다
- `client/android/key.properties`·keystore 는 절대 커밋하지 않는다(릴리스 때 볼륨 마운트). 배포 빌드는 `--obfuscate`(§3.2)
