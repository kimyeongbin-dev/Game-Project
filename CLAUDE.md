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

## 진행 상태 — 리팩토링 중

| 영역 | 상태 |
| :-- | :-- |
| 디렉토리 구조 / Docker 환경 | 완료 |
| `server/app/games/maze/` | 구 Quoridor 구현이 **명칭 그대로** 이동된 상태. 도메인 리네이밍 미적용 |
| `server/app/api/quoridor.py`, `schemas/quoridor.py`, `services/quoridor_service.py` | 구 REST API. 1인칭 미로 명세(§4.1)로 재설계 예정 |
| `server/app/core/`, `server/app/ws/` | 골격만 존재 |
| `client/lib/**` | 디렉토리 골격 + 허브 placeholder만 존재 |
| 나머지 5종 게임 | 미착수 |

**다음 단계:** 통합 플랫폼 및 게임별 API 설계서 작성 → 설계서 기반 리팩토링·구현. 구조 변경이나 대규모 코드 작성 전에는 플랜을 먼저 세운다.

## 주의사항
- `docs/quoridor/`는 재설계 대기 중인 **구 API 문서**다. 새 작업의 근거로 삼지 않는다.
- `client/android/key.properties`와 keystore는 절대 커밋하지 않는다. 릴리스 빌드 시 볼륨 마운트로 주입한다.
- 배포 빌드에는 `--obfuscate` 옵션을 적용한다 (§3.2).
