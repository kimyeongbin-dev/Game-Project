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
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]

# -----------------------------------------------------------------------------
FROM base AS test

COPY --from=deps-dev /opt/venv /opt/venv
COPY . .

CMD ["pytest", "-v", "--tb=short"]

# -----------------------------------------------------------------------------
FROM base AS prod

RUN groupadd --system gamemoa && useradd --system --gid gamemoa --no-create-home gamemoa

COPY --from=deps /opt/venv /opt/venv
COPY --chown=gamemoa:gamemoa pyproject.toml uv.lock ./
COPY --chown=gamemoa:gamemoa app ./app

USER gamemoa
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=4).status==200 else 1)"

# 워커는 1개로 고정한다.
#
# 현재 WebSocket 계층(app/ws/)의 매치메이킹 큐·방 상태·연결 맵이 모두
# 프로세스 내 모듈 전역 dict 이므로, 워커가 2개 이상이면 워커마다 별개의
# 큐와 방이 생겨 매칭이 깨진다.
#
# 워커를 늘리려면 PLATFORM_ARCHITECTURE.md §2.2 대로 상태를 Redis 로 옮기고
# 워커 간 브로드캐스트를 Pub/Sub 으로 처리하는 작업이 선행되어야 한다.
#
# WS 플래그는 app/core/config.py 의 ws_ping_interval_sec·ws_ping_timeout_sec·ws_max_size_bytes 와
# 같아야 한다(tests/test_dockerfile_flags.py). 반개방 끊김은 간격 + 타임아웃 + 10 s 뒤에 감지된다.
CMD ["uvicorn", "app.main:app", \
     "--host", "0.0.0.0", "--port", "8000", \
     "--workers", "1", \
     "--ws-ping-interval", "5", "--ws-ping-timeout", "5", "--ws-max-size", "4096", \
     "--proxy-headers", "--forwarded-allow-ips", "*"]
