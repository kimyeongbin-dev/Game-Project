# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**게임모아 (gamemoa)** — 크로스플랫폼 통합 미니게임 플랫폼. 벤토 그리드 로비에서 6종 보드·퍼즐 게임에 접속한다.

**단일 기준 문서(SSOT): [`PLATFORM_ARCHITECTURE.md`](PLATFORM_ARCHITECTURE.md)** — 기술 스택, 보안 원칙, 게임별 구현 명세, 디렉토리 청사진이 모두 여기에 있다. 구조나 스택에 관한 판단은 이 문서를 우선한다.

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
| `core/` | 환경변수, 카카오 OIDC 검증, JWT, 보안 *(골격 — 미구현)* |
| `db/` | PostgreSQL (SQLAlchemy 2.0 async) 설정·모델·리포지토리 |
| `api/` | REST 라우터 |
| `ws/` | 실시간 멀티플레이 WebSocket 핸들러 *(골격 — 미구현)* |
| `schemas/` | Pydantic 요청·응답 스키마 |
| `services/` | 비즈니스 로직, 서버 권위 검증. `services/scheduler/`는 일일 랭킹 리셋 |
| `games/maze/` | 1인칭 미로 **서버 권위 판정 엔진** (순수 Python, 프레임워크 무의존) |

- import는 항상 `app.` 절대 경로를 쓴다 (`from app.db.repository import ...`). `sys.path` 조작 금지.
- 테스트는 `server/tests/` 에 소스 구조를 반영한다: `tests/api/`, `tests/games/maze/`.

### 알아둘 설계 패턴
- **Graceful Degradation**: DB 연결 실패 시 서버는 메모리 전용 모드로 계속 동작한다. DB 작업 전에 `is_db_available()`을 확인한다.
- **게임 상태 직렬화**: `GameState.to_dict()` / `from_dict()`로 DB 영속화.
- **서비스 싱글톤**: `quoridor_service` 인스턴스가 게임 상태를 관리한다.
- **하드웨어 금고 키 보관**: AES/HMAC 키를 소스에 하드코딩하지 않는다. 앱 최초 실행 시 기기 내부에서 난수 생성해 Keystore/Keychain에만 보관한다 (§3.2).
- **개수를 박지 않는다**: 인원·게임·모드 수를 코드나 스키마에 고정값으로 쓰지 않는다. 판단 기준은 "인원이 4명이 되면 무엇을 고쳐야 하는가?" — 행 추가 외에 변경이 필요하면 하드코딩이다 (`docs/api/platform.md` §5 확장성 원칙).

## 진행 상태 — 리팩토링 중

| 영역 | 상태 |
| :-- | :-- |
| 디렉토리 구조 / Docker 환경 | 완료 |
| `server/app/games/maze/` | 구 Quoridor 구현이 **명칭 그대로** 이동된 상태. 도메인 리네이밍 미적용 |
| `server/app/api/quoridor.py`, `schemas/quoridor.py`, `services/quoridor_service.py` | 구 REST API 9개. 1인칭 미로 명세(§4.1)로 재설계 예정. 리플레이·히스토리 5개는 폐기 완료 |
| `server/app/core/` | `config.py`(환경변수 단일 진입점), `time.py`(표준 utcnow) |
| Redis | 연결 계층(`app/db/redis.py`) + lifespan 배선 완료. graceful degradation |
| 레이트 리미터 | **배선 완료** — Redis 저장소, 커스텀 429, `main.py` 등록. 테스트 10건 |
| `server/app/ws/` | 구 Quoridor 2P 구현 이식 완료 (약 1,600줄 + 테스트 1,220줄). **상태가 프로세스 내 dict 이라 Redis 이전 필요·1:1 전용.** `main.py` 미등록 |
| `client/lib/**` | 디렉토리 골격 + 허브 placeholder만 존재 |
| 나머지 5종 게임 | 미착수 |

**API 계약:** [`docs/api/platform.md`](docs/api/platform.md) (인증·병합·프로필·MMR), [`docs/api/games/maze.md`](docs/api/games/maze.md) (1인칭 미로 WS·Fog of War). 각 문서 말미에 미결 사항이 정리돼 있다.

**남은 작업과 TODO:** [`docs/ROADMAP.md`](docs/ROADMAP.md). 구조 변경이나 대규모 코드 작성 전에는 플랜을 먼저 세우고, 완료 후 [`docs/plans/`](docs/plans/README.md) 로 옮긴다 (규약은 그 README).

## 설정과 의존 서비스

**환경변수는 `app/core/config.py` 한 곳에서만 읽는다.** `os.getenv` 를 코드에 흩뿌리지 않는다 — 기본값이 분산되고 어떤 값이 실제로 쓰이는지 추적할 수 없게 된다.

```python
from app.core.config import settings
settings.redis_url, settings.rate_limit_per_minute, ...
```

Redis 논리 DB 를 용도별로 분리한다: **0 = 앱 상태(큐/방/세션), 1 = 테스트, 2 = 레이트 리미터.** 리미터 카운터가 앱 상태와 같은 DB 를 쓰면 키 스캔·FLUSHDB 가 서로를 건드린다.

DB 와 Redis 모두 **graceful degradation** 이다 — 연결 실패로 기동이 막히지 않는다. Redis 를 쓰는 코드는 반드시 `is_redis_available()` 로 가드한다. 단 **멀티플레이는 Redis 없이 성립하지 않는다** (워커 간 상태 공유 불가).

상태 확인:
```bash
curl -s http://localhost:8000/health | python -m json.tool
# dependencies.database / dependencies.redis / rate_limit 을 함께 보고한다
```

### 레이트 리미터 주의점

- **핸들러는 반드시 동기 함수(`def`)여야 한다.** `SlowAPIMiddleware` 는 동기 컨텍스트에서 핸들러를 호출하고, 코루틴 함수를 발견하면 **조용히 slowapi 기본 응답으로 대체**한다. `async def` 로 바꾸면 커스텀 429 가 전혀 쓰이지 않는다 — `tests/api/test_rate_limit.py` 가 이 회귀를 잡는다.
- 저장소가 메모리로 강등되면 워커마다 따로 카운트해 실효 제한이 워커 수만큼 곱해진다. Redis 저장소 여부도 테스트가 검증한다.
- `get_remote_address` 는 프록시 뒤에서 프록시 IP 를 본다. prod CMD 의 `--proxy-headers --forwarded-allow-ips *` 가 `X-Forwarded-For` 를 반영해 교정한다.

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
2. **커밋 차단** — `.githooks/pre-commit` 이 레거시 경로 추적을 감지하면 커밋을 거부한다 (이관되지 않은 계획서도 함께 검사한다). 클론 후 1회 활성화: `git config core.hooksPath .githooks`
3. **CI 차단** — `version-guard` 잡의 `scripts/check-legacy-paths.sh` 스텝

원격 히스토리에서 코드를 가져와야 할 때는 **머지하지 말고 내용만** 꺼낸다:
```bash
git show origin/develop:<구 경로> > <새 구조의 경로>
```

## 주의사항
- `docs/quoridor/`는 재설계 대기 중인 **구 API 문서**다. 새 작업의 근거로 삼지 않는다.
- `server/app/ws/` 는 구 Quoridor 2P 구현을 이식한 **재작업 기반**이다. 상태가 프로세스 내 dict 이고 Redis 를 쓰지 않아 §2.2 를 만족하지 못한다. 판정 내역은 `server/app/ws/__init__.py` 참조. `main.py` 에 라우터로 등록되어 있지 않다.
- `client/android/key.properties`와 keystore는 절대 커밋하지 않는다. 릴리스 빌드 시 볼륨 마운트로 주입한다.
- 배포 빌드에는 `--obfuscate` 옵션을 적용한다 (§3.2).
