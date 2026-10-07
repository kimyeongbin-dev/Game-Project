#!/usr/bin/env bash
# =============================================================================
# 프록시 경유 E2E — 운영 이미지·운영 설정으로 (M4-1). 로컬과 CI(.github/workflows/test-and-merge.yml proxy-e2e)가 이것을 부른다
#
#   bash scripts/e2e-proxy.sh            # 스택을 띄우고 e2e 를 돌린다(끝나도 내리지 않는다 — 로그를 보려면)
#   bash scripts/e2e-proxy.sh --down     # 끝나면 내린다(CI)
#
# - 운영 오버레이(docker-compose.prod.yml): server = prod 타깃(워커 2개, ENVIRONMENT=production, 오리진 없음)
# - 앞단 엣지가 없으므로 CADDY_TRUSTED_PROXIES=127.0.0.1/32(Caddy 컨테이너 자신 — 어떤 클라이언트의 XFF 도 믿지 않는다)
# - JWT 비밀키는 실행마다 무작위(production 은 32자 이상이 아니면 기동하지 않는다)
# - 개발 스택과 같은 compose 프로젝트·같은 이미지 이름(gamemoa-server)이다 — 개발 server(dev 타깃)가 prod 이미지로 바뀐다.
#   끝난 뒤 개발로 돌아가려면 **반드시 --build**: `docker compose up -d --build` (빌드 없이 올리면 prod 이미지를 그대로 써
#   --reload·소스 마운트 없이 뜬다 — 실측)
# =============================================================================
set -euo pipefail
cd "$(dirname "$0")/.."

export CADDY_TRUSTED_PROXIES="${CADDY_TRUSTED_PROXIES:-127.0.0.1/32}"
export JWT_SECRET_KEY="${E2E_JWT_SECRET_KEY:-$(python -c 'import secrets; print(secrets.token_hex(32))' 2>/dev/null || openssl rand -hex 32)}"
PROD=(-f docker-compose.yml -f docker-compose.prod.yml)

docker compose "${PROD[@]}" up -d --build --wait proxy
# server-test 는 운영 오버레이에서 꺼져 있다 — 기본 compose 로, 이미 뜬 스택에 의존성 없이 붙는다
docker compose build server-test
status=0
docker compose run --rm -T --no-deps -e E2E_BASE_URL=http://proxy:8080 server-test pytest e2e -v --tb=short || status=$?
if [ "${1:-}" = "--down" ]; then
  docker compose "${PROD[@]}" down -v
fi
exit "$status"
