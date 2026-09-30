# 🎮 게임모아 (gamemoa)

> **크로스플랫폼 통합 미니게임 플랫폼** — 벤토 그리드 로비에서 6종 보드·퍼즐 게임에 즉시 접속

[![Velog](https://img.shields.io/badge/Velog-통합%20게임%20플랫폼-20C997)](https://velog.io/@kimyeongbin/series/%ED%86%B5%ED%95%A9-%EA%B2%8C%EC%9E%84-%ED%94%8C%EB%9E%AB%ED%8F%BC)

**전체 설계는 [`PLATFORM_ARCHITECTURE.md`](PLATFORM_ARCHITECTURE.md) 를 참조하세요.** 기술 스택, 온/오프라인 하이브리드 보안 원칙, 게임별 구현 명세가 담긴 단일 기준 문서입니다.

---

## 하이브리드 플레이 모델

| 모드 | 로그인 | 네트워크 | 판정 주체 |
| :--- | :--- | :--- | :--- |
| **솔로 플레이** | 불필요 | 100% 오프라인 | 클라이언트 (로컬 AI / Isolate) |
| **멀티플레이 · 공유** | 카카오 로그인 필수 | 온라인 | **서버 권위** (전적·MMR은 서버만 기록) |

---

## 게임 라인업

| 게임 | 설명 |
| :--- | :--- |
| **1인칭 미로 대결** | 시야 제한(Fog of War) 미로 탐색 + 벽 설치. 1:1 / 1:1:1 |
| **낱말 퍼즐** | 3~6글자 다중 테마 크로스워드 (사자성어·신조어·우리말·외래어·고유명사·인물) |
| **퍼즐 맞추기** | 커스텀 사진 직소 퍼즐 + 다 맞춰야 열리는 시크릿 편지 |
| **합 10 퍼즐** | 드래그 제거 퍼즐. 역산 생성으로 클리어 보장 보드 제공 |
| **컬러 타일** | 교차점 동일 색상 타일 제거 퍼즐 |
| **오목** | 15×15 정통 오목, 국제 표준 렌주룰 (3-3 / 4-4 / 장목 금수) |

---

## 🛠 기술 스택

| 구분 | 기술 |
| :--- | :--- |
| **클라이언트** | Flutter 3.47 (Dart 3.13) · Flame Engine · Riverpod · Drift(SQLite) · Flutter Secure Storage |
| **서버** | FastAPI (Python 3.13) · SQLAlchemy 2.0 async · WebSocket |
| **데이터** | PostgreSQL 16 · Redis 8 · Cloudflare R2 |
| **개발·배포 환경** | Docker / Docker Compose (Flutter 버전은 `.flutter-version` 으로 단일 고정) |
| **CI/CD** | GitHub Actions |

---

## 🚀 빠른 시작

전제 조건: **Docker Desktop**, 그리고 실기기·에뮬레이터 실행용 **Flutter SDK 3.47+** (로컬)

```bash
# 1) 환경 변수 준비
cp .env.example .env    # POSTGRES_PASSWORD 등을 채운다

# 2) 서버 + DB + Redis 기동
docker compose up -d

# 3) 확인
curl http://localhost:8000/health
# API 문서: http://localhost:8000/docs

# 4) 클라이언트 실행 (로컬 Flutter — hot reload 필요)
cd client && flutter run -d chrome
```

### 테스트

```bash
docker compose run --rm server-test     # 서버 API + 게임 엔진 (pytest)
docker compose run --rm client-test     # flutter analyze + test
```

### 빌드

```bash
docker compose run --rm client-web                          # 웹 릴리스
docker compose --profile release run --rm android-builder    # Android AAB
docker build --target prod -t gamemoa-server ./server        # 서버 배포 이미지
```

자세한 환경 구성·트러블슈팅은 [`docs/환경.md`](docs/환경.md) 를 참조하세요.

---

## 📂 프로젝트 구조

```plaintext
.
├── PLATFORM_ARCHITECTURE.md    # 단일 기준 문서 (SSOT)
├── .flutter-version            # Flutter 버전 단일 기준 (로컬 = CI = 컨테이너)
├── docker-compose.yml          # 개발 환경 (server + db + redis + 테스트러너)
├── docker-compose.prod.yml     # 프로덕션 오버레이
├── infra/postgres/init/        # DB 초기화 스크립트
├── scripts/
│   └── check-flutter-version.sh  # 버전 드리프트 가드
│
├── client/                     # Flutter 클라이언트 (Android → iOS → Web)
│   ├── assets/{db,shaders,images}
│   └── lib/
│       ├── core/{auth,storage,network,security}
│       ├── hub/                # 벤토 그리드 로비
│       └── games/              # 6종 게임 모듈
│
└── server/                     # FastAPI 서버
    ├── pyproject.toml
    ├── Dockerfile              # dev / test / prod 멀티스테이지
    ├── app/
    │   ├── main.py
    │   ├── core/ db/ api/ ws/ schemas/ services/
    │   └── games/maze/         # 서버 권위 판정 엔진
    └── tests/{api,games}
```

---

## 📌 진행 상태

Phase 1 (Android 출시) 진행 중. 현재는 디렉토리 구조 및 Docker 환경 정비가 완료된 단계이며,
게임 구현은 API 설계서 확정 후 착수합니다. 세부 상태는 [`CLAUDE.md`](CLAUDE.md) 의 "진행 상태" 표를 참조하세요.
