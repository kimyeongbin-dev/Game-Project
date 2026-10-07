# =============================================================================
# 통합 미니게임 플랫폼 - 백엔드 서버 이미지
# PLATFORM_ARCHITECTURE.md §2.2 (FastAPI / Python 3.13+)
#
# 버전 고정 정책 — 자동 변경이 절대 일어나지 않도록
#   - 베이스 이미지: SHA256 다이제스트로 고정 (태그는 재발행되므로 신뢰하지 않음)
#   - 직접 의존성 : pyproject.toml 에서 모두 `==` 고정
#   - 전이 의존성 : uv.lock 에 URL + SHA256 해시까지 고정
#   - 설치        : `uv sync --frozen` — lock 과 어긋나면 해석하지 않고 실패
#   - uv 자체     : 아래 UV_VERSION 으로 고정
#   갱신은 scripts/update-image-digests.sh 와 `uv lock --upgrade` 로만 수행한다.
#
# 스테이지 구성
#   base      : 공통 런타임 (python + venv 경로)
#   deps      : 런타임 의존성 설치 (프로덕션용)
#   deps-dev  : deps + 테스트 의존성 (pytest)
#   dev       : 로컬 개발용 (소스 볼륨 마운트 + --reload)
#   test      : pytest 실행 전용
#   prod      : 배포용 (non-root, reload 없음, 소스 이미지에 포함)
#
# 사용 예
#   docker compose up server                     # dev
#   docker compose run --rm server-test          # test
#   docker build --target prod -t gamemoa-server .
# =============================================================================

# python:3.13-slim — 다이제스트 고정
ARG PYTHON_IMAGE=python:3.13-slim@sha256:7c61056e61ac89e852de05f3dc6fa51a6dd2181797bceed46aa725dd7cb2cd3b
ARG UV_VERSION=0.12.21

# -----------------------------------------------------------------------------
FROM ${PYTHON_IMAGE} AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    VIRTUAL_ENV=/opt/venv \
    PATH="/opt/venv/bin:$PATH" \
    PYTHONPATH=/srv/gamemoa

WORKDIR /srv/gamemoa

# -----------------------------------------------------------------------------
FROM base AS deps
ARG UV_VERSION

# C 확장 빌드용 (wheel 미제공 환경 대비)
RUN apt-get update \
 && apt-get install -y --no-install-recommends build-essential \
 && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir "uv==${UV_VERSION}"

ENV UV_PROJECT_ENVIRONMENT=/opt/venv \
    UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=0 \
    UV_NO_PROGRESS=1

# 의존성 레이어 캐싱: 소스 변경이 재설치를 유발하지 않도록
# pyproject.toml + uv.lock 만 먼저 복사한다.
# --frozen : lock 을 재해석하지 않는다 (pyproject 와 어긋나면 실패)
# --no-install-project : 프로젝트 자체는 제외하고 의존성만
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

# -----------------------------------------------------------------------------
FROM deps AS deps-dev
# dev 는 [project.optional-dependencies] 의 extra 이므로 --extra 로 명시해야 한다
# (uv sync 기본 동작은 extra 를 설치하지 않는다)
RUN uv sync --frozen --extra dev --no-install-project

# -----------------------------------------------------------------------------
FROM base AS dev

# 개발 편의: DB 헬스체크/수동 쿼리용 psql
RUN apt-get update \
 && apt-get install -y --no-install-recommends postgresql-client \
 && rm -rf /var/lib/apt/lists/*

COPY --from=deps-dev /opt/venv /opt/venv
COPY . .

EXPOSE 8000
# WS 플래그는 prod 와 같다(tests/test_dockerfile_flags.py) — 개발에서도 4 KiB 상한·ping 감지가 같게 재현된다
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload",      "--ws-ping-interval", "5", "--ws-ping-timeout", "5", "--ws-max-size", "4096"]

# -----------------------------------------------------------------------------
FROM base AS test

COPY --from=deps-dev /opt/venv /opt/venv
COPY . .

CMD ["pytest", "-v", "--tb=short"]

# -----------------------------------------------------------------------------
FROM base AS prod

# 운영 이미지의 기본 환경은 production — 변수를 빠뜨려도 운영 검증(오리진 fail-closed·JWT 키 길이·pubsub test 금지)이
# 꺼지지 않는다(M4-1 독립 검토). 개발·CI 는 compose 가 local·ci 를 명시한다. tests/test_dockerfile_flags.py 가 검사한다
ENV ENVIRONMENT=production

RUN groupadd --system gamemoa && useradd --system --gid gamemoa --no-create-home gamemoa

COPY --from=deps /opt/venv /opt/venv
COPY --chown=gamemoa:gamemoa pyproject.toml uv.lock ./
COPY --chown=gamemoa:gamemoa app ./app

USER gamemoa
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=4).status==200 else 1)"

# 워커 2개 (M3 완료 판정, 2026-10-06).
#
# 큐·방·게임 상태는 Redis 가 권위이고(M3 3단계), 워커 간 전달은 Pub/Sub(4단계), 좌석 소유는 연결 단위·
# 크래시는 워커 하트비트로 처리한다(6·7단계). 실제 uvicorn 워커 2개로 매칭·좌석별 전달·구독 끊김·워커 kill·
# 스위퍼 이중 처리·Redis 재시작/정지·SIGTERM 배포를 확인했다 —
# docs/research/2026-10-06-M3-7단계-다중워커-실측.md (하네스 server/harness/multiworker).
# 워커 분배는 고르지 않다(실측 E1, 85~99% 한 워커) — 용량 산정에 워커 수 × 균등을 가정하지 않는다.
# tests/test_dockerfile_flags.py 가 워커 수 하한(2)을 검사한다.
#
# WS 플래그는 app/core/config.py 의 ws_ping_interval_sec·ws_ping_timeout_sec·ws_max_size_bytes 와
# 같아야 한다(tests/test_dockerfile_flags.py). 반개방 끊김은 간격 + 타임아웃 + 10 s 뒤에 감지된다.
#
# 프록시 신뢰(M4-1): X-Forwarded-For 를 믿을 주소는 **환경변수 FORWARDED_ALLOW_IPS** — uvicorn 이 직접 읽는다(앱의
# app/core/config.py 단일 진입점 원칙의 예외). 값은 바로 앞 프록시(Caddy) 주소뿐이다. 미설정이면 uvicorn 기본 127.0.0.1 —
# 아무 XFF 도 믿지 않는다(fail-closed). `--forwarded-allow-ips *` 는 쓰지 않는다: 서버에 직접 닿는 누구든 IP 를 위조한다.
CMD ["uvicorn", "app.main:app", \
     "--host", "0.0.0.0", "--port", "8000", \
     "--workers", "2", \
     "--ws-ping-interval", "5", "--ws-ping-timeout", "5", "--ws-max-size", "4096", \
     "--proxy-headers"]
