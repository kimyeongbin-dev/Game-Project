# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

**응답 언어: 한국어.** 사용자에게 보이는 모든 텍스트(진행 보고·질문·최종 요약)는 한국어로 쓴다. 코드 식별자·명령어·커밋 해시는 그대로 둔다. 커밋 메시지·저장소 문서도 기존 관례대로 한국어다.

## Project Overview

**게임모아 (gamemoa)** — 크로스플랫폼 통합 미니게임 플랫폼. 벤토 그리드 로비에서 6종 보드·퍼즐 게임에 접속한다.

**단일 기준 문서(SSOT): [`PLATFORM_ARCHITECTURE.md`](PLATFORM_ARCHITECTURE.md)** — 기술 스택, 보안 원칙, 게임별 구현 명세, 디렉토리 청사진이 모두 여기에 있다. 구조나 스택에 관한 판단은 이 문서를 우선한다.

### 작업 재개 — 무엇을 언제 읽나 (통째로 읽지 말 것)

| 시점 | 읽을 것 | 목적 |
| :-- | :-- | :-- |
| 세션 시작 | 이 파일 + 메모리 인덱스(자동) → [`docs/ROADMAP.md`](docs/ROADMAP.md) 맨 위 "현재 위치" 문단과 진행 중인 마일스톤 절만 | 다음 할 일 |
| 계획 수립 | [`docs/plans/README.md`](docs/plans/README.md) "검증 관문과 독립 검토"·"모델 분할 표시" → **직전 계획서의 상태 머리글**(계획 이탈·계획 오류 = 반복하지 말 것) | 규약·교훈 |
| 이관 항목을 다룰 때 | ROADMAP 항목이 가리키는 `docs/research/*독립검토*.md` 의 **채택표 해당 행만**, 필요하면 그 원문 항목 | 지적의 원래 근거 |
| 동작·수치를 인용할 때 | `docs/research/*실측*.md` 의 "알려진 한계"·해당 시나리오 절 | 실측 근거(추정 금지) |
| 와이어·키·규칙 | `docs/api/games/maze.md`·`docs/api/platform.md` 의 해당 절(§ 번호로) | 설계 정본 |

계획서 본문·검토 원문 전체·결과 원자료(`server/harness/multiworker/results/`, git 밖)는 근거를 확인할 때만 연다.

### 핵심 운영 정책 (Hybrid Play Model)
- **솔로 플레이**: 비로그인 / 100% 오프라인. 게임 루프·판정·로컬 AI·세이브가 전부 클라이언트 내부에서 수행된다.
- **멀티플레이 및 공유**: 카카오 로그인 필수 / 온라인. 승패·전적·MMR은 **반드시 서버가 판정**하고 클라이언트 주장은 신뢰하지 않는다 (Zero-Trust, §3.3 원칙 2).

## 개발 환경 — 모든 것이 Docker

로컬에 Python/Postgres/Redis를 설치하지 않는다. `.env.example` → `.env` 복사 후:

```bash
# 개발 서버 (db + redis + FastAPI hot reload)
docker compose up -d
docker compose logs -f server

# 서버/게임엔진 테스트 (전용 gamemoa_test DB 사용)
docker compose run --rm server-test

# 특정 테스트만
docker compose run --rm server-test pytest tests/games -q

# Flutter 정적 분석 + 테스트 (CI와 동일 환경)
docker compose run --rm client-test

# 웹 릴리스 빌드
docker compose run --rm client-web

# Android 릴리스 AAB (이미지 수 GB, 릴리스 컷 시점에만)
docker compose --profile release run --rm android-builder

# 프로덕션 이미지 로컬 검증
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d
```

**컨테이너에서 불가능한 것 — 로컬 Flutter로 실행한다:**
```bash
cd client
flutter run -d chrome          # 웹
flutter run -d <device>         # 에뮬레이터/실기기 + hot reload
dart run build_runner build     # drift / riverpod 코드 생성
```
이유: 컨테이너는 USB 패스스루/GUI를 지원하지 않는다.

## 버전 고정 — 자동 변경은 절대 없다

모든 버전이 고정되어 있고, **`scripts/check-version-pinning.sh` 가 규율 위반을 검사**한다 (CI `version-guard` 잡).

| 대상 | 고정 방식 |
| :-- | :-- |
| 서버 직접 의존성 | `server/pyproject.toml` 전부 `==` |
| 서버 **전이** 의존성 | `server/uv.lock` — URL + SHA256 해시까지. `uv sync --frozen` 으로 설치 |
| `uv` 자체 | `server/Dockerfile` 의 `ARG UV_VERSION` |
| 컨테이너 베이스 이미지 | `name:tag@sha256:<digest>` — 태그는 가독성용, 실제로 받는 것은 다이제스트 |
| Flutter SDK | `.flutter-version` |
| Flutter 패키지 | `client/pubspec.yaml` 정확 버전 (캐럿 금지) + `pubspec.lock` |
| Dart SDK 제약 | `client/pubspec.yaml` 의 `sdk: 3.13.4` (정확) |
| 린트 플러그인 | `client/analysis_options.yaml` 의 `plugins:` 정확 버전 |
| Android SDK | `compileSdk`/`minSdk`/`targetSdk`/`ndkVersion` 명시 고정 (`flutter.*` 위임 금지) |
| GitHub Actions | 40자 커밋 SHA (`@v4` 같은 이동 태그 금지) |

**의존성을 바꿀 때:**
```bash
# 서버 — pyproject.toml 수정 후 lock 재생성 (컨테이너에서)
docker run --rm -v "$PWD/server:/w" -w /w   python:3.13-slim@sha256:7c61056e61ac89e852de05f3dc6fa51a6dd2181797bceed46aa725dd7cb2cd3b   sh -c 'pip install -q uv==0.12.21 && uv lock --no-progress'
docker compose build server-test && docker compose run --rm server-test

# 클라이언트 — pubspec.yaml 을 정확 버전으로 수정 후
cd client && flutter pub get && flutter analyze && flutter test

# 베이스 이미지 다이제스트 — 업스트림 변경 점검 / 갱신
bash scripts/update-image-digests.sh          # 점검만
bash scripts/update-image-digests.sh --write  # 갱신 후 반드시 재빌드+테스트
```

`flutter pub upgrade` 는 쓰지 않는다 — 정확 고정을 무너뜨린다. 올릴 때는 `pubspec.yaml` 의 숫자를 직접 바꾼다.

### Flutter 버전 — 단일 기준 `.flutter-version`

로컬·CI·컨테이너가 **동일한 Flutter 바이너리**를 쓴다. 기준은 저장소 루트 `.flutter-version` (현재 3.47.5 / Dart 3.13.4) 하나다.

```bash
bash scripts/check-flutter-version.sh   # 기준 / Dockerfile / 로컬 SDK 3자 비교
```

- `client/Dockerfile` 이 Google 공식 릴리스 아카이브에서 해당 버전을 설치한다(sha256 검증). 제3자 이미지는 쓰지 않는다 — Flutter 릴리스를 여러 마이너 버전 뒤늦게 따라오고, Dart 버전이 `pubspec.yaml` 의 `sdk:` 제약을 만족하지 못한다.
- CI의 `version-guard` 잡이 불일치를 가장 먼저 실패시킨다.
- **`pubspec.yaml` 의 `environment: sdk:` 제약을 낮춰 낡은 툴체인을 통과시키지 말 것.** 이미지를 프로젝트에 맞춘다.
- 버전 상향 순서: 로컬 `flutter upgrade` → `.flutter-version` → `client/Dockerfile` ARG → `docker-compose.yml` 기본값 → 가드 확인 → `flutter pub get` → 컨테이너 `--no-cache` 재빌드.

**API Base URL (클라이언트에서 Docker 서버 접속):** Web/iOS 시뮬레이터 `http://localhost:8000`, Android 에뮬레이터 `http://10.0.2.2:8000`, 실기기 `http://<PC IP>:8000`

**호스트 :8000 은 리버스 프록시(Caddy, `infra/caddy/Caddyfile`)다**(M4-1). server 컨테이너는 호스트 포트를 열지 않는다 — 로컬·CI·배포가 같은 경로(Caddy → uvicorn)를 탄다. 네트워크는 고정 서브넷(`GAMEMOA_SUBNET`, 기본 `10.231.0.0/24` — Docker 기본 주소 풀 밖)이고 proxy 는 고정 주소(`GAMEMOA_PROXY_IP`, `.10`)다 — 호스트의 다른 네트워크(VPN 등)와 겹치면 `GAMEMOA_SUBNET`·`GAMEMOA_DYNAMIC_RANGE`·`GAMEMOA_PROXY_IP` 를 `.env` 에서 함께 바꾼다. 네트워크 설정이 바뀌면 `docker compose down` 후 다시 올린다.

**운영 이미지는 기본 `ENVIRONMENT=production`** 이다(prod 스테이지 `ENV`) — 오리진 fail-closed·JWT 키 32자·pubsub `test` 금지가 켜진다. 운영 오버레이는 `CADDY_TRUSTED_PROXIES`(엣지 대역)를 필수로 받는다.
```bash
bash scripts/e2e-proxy.sh            # 프록시 경유 E2E — 운영 이미지·운영 설정(CI proxy-e2e 와 같은 스크립트)
docker compose up -d --build         # 그 뒤 개발로 복귀 — 반드시 --build(같은 이미지 이름이라 prod 이미지를 재사용한다)
bash scripts/check-proxy-config.sh                                                  # 신뢰 경계·토큰 로그 가드
```

## 아키텍처

### 모노레포 2분할
```
client/          # Flutter (Dart) — Android → iOS → Web
server/          # FastAPI (Python 3.13+)
infra/           # 컨테이너 초기화 스크립트
```

### client/lib 의존 방향
```
hub/ ──┐
       ├──> core/          (auth, storage, network, security)
games/ ┘
```
- `core/`는 어떤 게임 모듈도 참조하지 않는다 (단방향).
- 게임 모듈 간 직접 참조 금지. 공통 기능은 `core/`를 경유한다.
- 무거운 연산(로컬 AI 수읽기, 역산 보드 생성, 이미지 분할)은 **반드시 `Dart Isolate`로 분리**해 UI 프레임을 방어한다.
- 각 디렉토리에 책임 범위를 적은 `README.md`가 있다. 새 코드를 넣기 전에 읽는다.

### server/app 계층
| 디렉토리 | 책임 |
| :-- | :-- |
| `main.py` | FastAPI 엔트리포인트, lifespan (DB 초기화 / 스케줄러) |
| `core/` | 환경변수, JWT access token 검증, 로그 마스킹, 시계·워커 id *(카카오 OIDC·토큰 발급은 미구현 — 인증 작업)* |
| `db/` | PostgreSQL (SQLAlchemy 2.0 async) 설정·모델·리포지토리 |
| `api/` | REST 라우터 |
| `ws/` | 실시간 멀티플레이 WebSocket — 핸들러·와이어·런타임(lifespan)·레이트 리밋·구독 버스 |
| `schemas/` | Pydantic 요청·응답 스키마 |
| `services/` | 비즈니스 로직, 서버 권위 검증 |
| `games/maze/` | 1인칭 미로 **서버 권위 판정 엔진** (순수 Python, 프레임워크 무의존) |

- import는 항상 `app.` 절대 경로를 쓴다 (`from app.db.repository import ...`). `sys.path` 조작 금지.
- 테스트는 `server/tests/` 에 소스 구조를 반영한다: `tests/api/`, `tests/games/maze/`.

### 알아둘 설계 패턴
- **Graceful Degradation**: DB 연결 실패 시 서버는 메모리 전용 모드로 계속 동작한다. DB 작업 전에 `is_db_available()`을 확인한다.
- **게임 상태 직렬화**: `GameState.to_dict()` / `from_dict()` 가 Redis `game:<id>:state` 값 전체다(M3 3단계에서 저장). `schema_version` 이 다르면 복원을 거부한다.
- **멀티플레이 상태는 Redis 에만**: `services/maze_game.py`(게임 상태·락·종료 기록), `services/matchmaking.py`(큐), `services/rooms.py`(방), `services/activity.py`(유저당 활동 하나). 서비스 인스턴스는 상태를 갖지 않는다. 상태를 쓴 직후 `services/events.py` 로 이벤트를 **발행만** 하고(권위 없음, at-most-once), 워커마다 `ws/bus.py` 가 구독해 자기 소켓에만 보낸다. 좌석별 누적 시야(`game:{id}:vision:{seat_no}`)는 수락된 행동마다 state 와 **같은 락 토큰의 펜싱 쓰기 한 번**(`fenced_mset`)으로 기록하고, 화면(`services/maze_view.py`)은 자기 좌석 관측만 읽는다. 시계(`game:{id}:clocks`)와 데드라인 색인(`deadlines:{game}`)도 같은 쓰기 한 번(`fenced_write`)이고, 시각은 Redis `TIME` 이다. **게임 이벤트 발행도 그 쓰기와 같은 Lua 안의 `PUBLISH`** 다(`RedisPublisher.in_commit` — 쓰기 직후·발행 전 워커가 죽으면 통지가 영영 사라졌다, M4-1). 발행 경로를 바꿀 때 이 원자성을 깨지 말 것. 만료는 워커마다 도는 `services/sweeper.py` 가 리스 클레임으로 꺼내고 게임 락 안에서 다시 계산한다(점수는 힌트). 키는 `app/db/redis_keys.py` 에서만 만들고, 스키마 표는 `docs/api/platform.md` "Redis 키 스키마"에 있다.
- **하드웨어 금고 키 보관**: AES/HMAC 키를 소스에 하드코딩하지 않는다. 앱 최초 실행 시 기기 내부에서 난수 생성해 Keystore/Keychain에만 보관한다 (§3.2).
- **개수를 박지 않는다**: 인원·게임·모드 수를 코드나 스키마에 고정값으로 쓰지 않는다. 판단 기준은 "인원이 4명이 되면 무엇을 고쳐야 하는가?" — 행 추가 외에 변경이 필요하면 하드코딩이다 (`docs/api/platform.md` §5 확장성 원칙).

## 진행 상태 — 리팩토링 중 (인프라 M4-1 완료, 다음 M4-2)

| 영역 | 상태 |
| :-- | :-- |
| 디렉토리 구조 / Docker 환경 | 완료 |
| `server/app/games/maze/` | **N인 좌석 모델로 일반화 완료**(M3 1단계) — 모드별 배치 테이블 `core/layouts.py`, 점프 제거, 탈락·`last_standing`·순위·턴당 거절 카운터. 2·3·4좌석 파라미터화 테스트(`test_seat_scaling.py`). **시야 엔진 완료**(M3 5단계) — `core/vision.py`(3×3 + 벽 차폐, 단위 변, 누적 관측). 도메인 리네이밍 미적용 |
| 구 REST `/api/v1/quoridor/*` | **폐기 완료**(M3 1단계). shim `quoridor_service` 도 3단계에서 삭제 |
| 큐·방·게임 상태 | **Redis 이전 완료**(M3 3단계) — 게임별 락 + 펜싱 쓰기, Lua 원자 매칭, N인 좌석. 종료 시 `game_sessions` 기록. 2·3·4좌석 파라미터화 테스트 |
| `server/app/db/` | **2인 전제 제거 완료**(M3 2단계) — `game_sessions` 는 시작·종료 기록만, 좌석은 `game_participants` 행. `match_queue`·`game_rooms`·`daily_champions`·스케줄러 폐기. 마이그레이션 도구 없음(`create_all`) — Alembic 은 첫 운영 배포 전 |
| `server/app/core/` | `config.py`(환경변수 단일 진입점), `time.py`(표준 utcnow·Redis TIME 시계), `security.py`(access token **검증만** — 발급은 인증 작업), `redaction.py`(로그의 `token=` 마스킹), `worker.py`(워커 id) |
| Redis | 연결 계층(`app/db/redis.py`) + lifespan 배선 완료. graceful degradation. **연결은 해석해 둔 주소로**(`AddressBook`·`PinnedConnection`, M4-1 — Redis 가 꺼진 동안의 느린 이름 조회가 재접속을 막지 않게). 새 Redis 클라이언트를 만들 때 `connection_class=PinnedConnection` |
| 레이트 리미터 | **배선 완료** — Redis 저장소, 커스텀 429, `main.py` 등록. 테스트 10건. 프록시 경유 IP 정확도는 M4-1 하네스 P1 |
| 리버스 프록시 | **M4-1 완료** — Caddy(`infra/caddy/Caddyfile`, TLS 는 엣지), 신뢰 경계(Caddy → uvicorn), CORS·WS Origin(운영 fail-closed), WS IP 접속 리밋, 프록시 경유 E2E(`server/e2e`, CI `proxy-e2e`) |
| `server/app/ws/` | **완료**(M3 7단계) — `maze_handler`(`/api/v1/ws/maze`, §12 10종·인증 4001~4003·accept 후 close), `delivery`·`wire`(내부 이벤트 → §12 와이어, 게임별 `version`), `runtime`(lifespan: 버스·스위퍼·큐 티커·SIGTERM 기준 서버 유예·끊김 재시도), `rate_limit`(소켓 버킷·접속 카운터), `connection_manager`(연결 맵, 같은 계정은 클러스터에 하나). 좌석 소유는 연결 id 단위. 독립 검토 #1~#3 반영 |
| 시간 체계 | **완료**(M3 6단계) — `services/maze_clock.py`(두 시계 분리, 지연 정산), `services/sweeper.py`(리스 클레임, 장애 구간, 유실 점검), `ws/server_grace.py`(서버 유예 소급). Redis 장애는 전역 하트비트(`store:alive` — 워커마다 전용 200 ms 루프·전용 연결, 7단계 실측), 크래시 워커의 좌석은 워커 하트비트(`store:workers`)로 처리. 독립 검토 반영(`docs/research/2026-10-04-M3-6단계-독립검토.md`). 스위퍼·유예의 lifespan 배선은 7단계 완료 |
| `client/lib/**` | 디렉토리 골격 + 허브 placeholder만 존재 |
| 나머지 5종 게임 | 미착수 |

**API 계약:** [`docs/api/platform.md`](docs/api/platform.md) (인증·병합·프로필·MMR), [`docs/api/games/maze.md`](docs/api/games/maze.md) (1인칭 미로 WS·Fog of War). 각 문서 말미에 미결 사항이 정리돼 있다.

**남은 작업과 TODO:** [`docs/ROADMAP.md`](docs/ROADMAP.md). 구조 변경이나 대규모 코드 작성 전에는 플랜을 먼저 세운다. 계획서는 [`docs/plans/`](docs/plans/README.md) 에 생성되며(`plansDirectory` 설정 — 클론당 1회), 완료 후 이름·상태 머리글을 규약대로 정리한다.

## 설정과 의존 서비스

**환경변수는 `app/core/config.py` 한 곳에서만 읽는다.** `os.getenv` 를 코드에 흩뿌리지 않는다 — 기본값이 분산되고 어떤 값이 실제로 쓰이는지 추적할 수 없게 된다.

```python
from app.core.config import settings
settings.redis_url, settings.rate_limit_per_minute, ...
```

Redis 논리 DB 를 용도별로 분리한다: **0 = 앱 상태(큐/방/세션), 1 = 테스트, 2 = 레이트 리미터.** 리미터 카운터가 앱 상태와 같은 DB 를 쓰면 키 스캔·FLUSHDB 가 서로를 건드린다.

**Pub/Sub 채널은 논리 DB 로 격리되지 않는다**(서버 전역). 채널은 `PUBSUB_NAMESPACE` 로 명시적으로 나눈다: **`app` = 앱, `test` = 테스트** (`docker-compose.yml` 의 server / server-test). 테스트 픽스처는 `test` 가 아니면 중단하고, production 은 `test` 로 기동하지 않는다.

DB 와 Redis 모두 **graceful degradation** 이다 — 연결 실패로 기동이 막히지 않는다. Redis 를 쓰는 코드는 반드시 `is_redis_available()` 로 가드한다. 단 **멀티플레이는 Redis 없이 성립하지 않는다** (워커 간 상태 공유 불가).

상태 확인:
```bash
curl -s http://localhost:8000/health | python -m json.tool
# dependencies.database / dependencies.redis / rate_limit 을 함께 보고한다
```

### 레이트 리미터 주의점

- **핸들러는 반드시 동기 함수(`def`)여야 한다.** `SlowAPIMiddleware` 는 동기 컨텍스트에서 핸들러를 호출하고, 코루틴 함수를 발견하면 **조용히 slowapi 기본 응답으로 대체**한다. `async def` 로 바꾸면 커스텀 429 가 전혀 쓰이지 않는다 — `tests/api/test_rate_limit.py` 가 이 회귀를 잡는다.
- 저장소가 메모리로 강등되면 워커마다 따로 카운트해 실효 제한이 워커 수만큼 곱해진다. Redis 저장소 여부도 테스트가 검증한다.
- **리밋 키는 실제 클라이언트 IP 다(M4-1).** Caddy 가 신뢰한 엣지(`CADDY_TRUSTED_PROXIES`)의 `X-Forwarded-For` 로 클라이언트를 판정해 그 주소 하나로 다시 쓰고(`header_up X-Forwarded-For {client_ip}`), uvicorn 은 **환경변수 `FORWARDED_ALLOW_IPS` = proxy 주소**에서 온 값만 믿는다. 이 변수는 앱이 아니라 uvicorn 이 직접 읽는다 — "환경변수는 `config.py` 에서만" 원칙의 유일한 예외다. **`--forwarded-allow-ips *` 를 쓰지 않는다** — 서버에 닿는 누구든 IP 를 위조한다(`scripts/check-proxy-config.sh`·CI 가 막는다).

## 폐기된 레거시 경로 — 되살리지 않는다

`backend_fastapi/`, `frontend_flutter/`, `games/` 는 2026-09-30 구조 재편으로 영구 폐기되었다.

```
backend_fastapi/  →  server/
frontend_flutter/ →  client/
games/            →  server/app/games/maze/
```

`origin/develop` 과 `origin/dev-test` 는 **이 경로들에 파일을 가진 히스토리**다. 잘못 머지하면 구 구조가 되살아난다.

**3중 차단이 걸려 있다:**
1. **ancestry 차단** — `feature/platform-restructure` 에서 두 원격 브랜치를 `git merge -s ours` 로 머지해 조상으로 편입했다. 따라서 이후 `git merge develop` 은 no-op 이며 구 경로를 되살릴 수 없다.
2. **커밋 차단** — `.githooks/pre-commit` 이 레거시 경로 추적을 감지하면 커밋을 거부한다 (계획서 규약도 함께 검사한다). 클론 후 1회 활성화: `git config core.hooksPath .githooks`
3. **CI 차단** — `version-guard` 잡의 `scripts/check-legacy-paths.sh` 스텝

원격 히스토리에서 코드를 가져와야 할 때는 **머지하지 말고 내용만** 꺼낸다:
```bash
git show origin/develop:<구 경로> > <새 구조의 경로>
```

## 주의사항
- `docs/quoridor/`는 재설계 대기 중인 **구 API 문서**다. 새 작업의 근거로 삼지 않는다.
- **prod 는 `--workers 2`** 다(M3 완료 판정, `docs/research/2026-10-06-M3-7단계-다중워커-실측.md`). 다중 워커 동작을 바꾸면 하네스 `server/harness/multiworker/`(실제 워커 2개 + Redis 장애)를 다시 돌린다 — pytest 는 한 프로세스라 워커 간 경합·신호·실제 장애를 재현하지 못한다. 좌석 owner 는 **연결 id**(`<worker_id>:<토큰>`)이고 끊김은 그 연결일 때만 기록된다.
- `client/android/key.properties`와 keystore는 절대 커밋하지 않는다. 릴리스 빌드 시 볼륨 마운트로 주입한다.
- 배포 빌드에는 `--obfuscate` 옵션을 적용한다 (§3.2).
