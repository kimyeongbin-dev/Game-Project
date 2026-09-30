# =============================================================================
# 통합 미니게임 플랫폼 - 백엔드 서버 이미지
# PLATFORM_ARCHITECTURE.md §2.2 (FastAPI / Python 3.13+)
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
ARG PYTHON_VERSION=3.13

# -----------------------------------------------------------------------------
FROM python:${PYTHON_VERSION}-slim AS base

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

# C 확장 빌드용 (hiredis, cryptography 등 wheel 미제공 환경 대비)
RUN apt-get update \
 && apt-get install -y --no-install-recommends build-essential \
 && rm -rf /var/lib/apt/lists/*

RUN python -m venv "$VIRTUAL_ENV" && pip install --upgrade pip setuptools wheel

# 의존성 레이어 캐싱: 소스 변경이 의존성 재설치를 유발하지 않도록
# pyproject.toml 만 먼저 복사하고 패키지 스텁으로 설치한다.
# (실제 소스는 이후 스테이지에서 /srv/gamemoa 로 덮어써지고, PYTHONPATH 로 해석된다)
COPY pyproject.toml ./
RUN mkdir -p app && : > app/__init__.py \
 && pip install -e "."

# -----------------------------------------------------------------------------
FROM deps AS deps-dev
RUN pip install -e ".[dev]"

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
COPY --chown=gamemoa:gamemoa pyproject.toml ./
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
CMD ["uvicorn", "app.main:app", \
     "--host", "0.0.0.0", "--port", "8000", \
     "--workers", "1", \
     "--proxy-headers", "--forwarded-allow-ips", "*"]
