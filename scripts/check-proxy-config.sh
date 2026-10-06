#!/usr/bin/env bash
# =============================================================================
# 프록시 신뢰 경계·토큰 로그 가드 (M4-1)
#
#   bash scripts/check-proxy-config.sh      # 위반이 있으면 exit 1
#
# 검사
#   1. Caddyfile 에 `log` 지시어가 없다 — URI 의 ?token= 이 접속 로그로 샌다(maze.md §2)
#   2. Caddyfile: admin off · auto_https off(TLS 는 엣지) · 신뢰 대역과 업스트림이 환경변수
#   3. compose: server 가 호스트 포트를 열지 않는다(Caddy 를 우회하는 경로 없음)
#   4. compose: server 의 FORWARDED_ALLOW_IPS 기본값 = proxy 의 고정 주소 기본값
#   5. 어디에도 `--forwarded-allow-ips *` 가 없다(Dockerfile·compose·하네스)
# =============================================================================
set -u
cd "$(dirname "$0")/.."

CADDYFILE=infra/caddy/Caddyfile
COMPOSE=docker-compose.yml
fail=0
bad() { echo "  FAIL  $*"; fail=1; }
ok() { echo "  OK    $*"; }

# 주석 줄을 뺀 Caddyfile 본문
body="$(grep -vE '^[[:space:]]*#' "$CADDYFILE")"

if grep -qE '^[[:space:]]*log([[:space:]]|$|\{)' <<<"$body"; then
  bad "$CADDYFILE: 'log' 지시어 — 쿼리의 토큰이 접속 로그로 샌다"
else
  ok "$CADDYFILE: 접속 로그 없음"
fi
grep -qE '^[[:space:]]*admin[[:space:]]+off' <<<"$body" && ok "$CADDYFILE: admin off" || bad "$CADDYFILE: admin off 없음"
grep -qE '^[[:space:]]*auto_https[[:space:]]+off' <<<"$body" && ok "$CADDYFILE: auto_https off" || bad "$CADDYFILE: auto_https off 없음(TLS 는 엣지)"
grep -qF 'trusted_proxies static {$CADDY_TRUSTED_PROXIES' <<<"$body" && ok "$CADDYFILE: 신뢰 대역 = 환경변수" || bad "$CADDYFILE: trusted_proxies 가 환경변수가 아니다"
grep -qF 'reverse_proxy {$CADDY_UPSTREAM' <<<"$body" && ok "$CADDYFILE: 업스트림 = 환경변수" || bad "$CADDYFILE: 업스트림이 환경변수가 아니다"

# compose 의 server 서비스 블록(다음 2칸 들여쓰기 서비스 이름 전까지)
server_block="$(awk '/^  server:$/{on=1; next} on && /^  [a-z][a-z0-9_-]*:$/{exit} on' "$COMPOSE")"
if grep -qE '^    ports:' <<<"$server_block"; then
  bad "$COMPOSE: server 가 호스트 포트를 연다 — proxy 를 우회한다"
else
  ok "$COMPOSE: server 호스트 포트 없음"
fi
trust="$(grep -oE 'FORWARDED_ALLOW_IPS: *\$\{GAMEMOA_PROXY_IP:-[0-9.]+\}' <<<"$server_block" | grep -oE '[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+')"
proxy_ip="$(awk '/^  proxy:$/{on=1; next} on && /^  [a-z][a-z0-9_-]*:$/{exit} on' "$COMPOSE" |
  grep -oE 'ipv4_address: *\$\{GAMEMOA_PROXY_IP:-[0-9.]+\}' | grep -oE '[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+')"
if [ -n "$trust" ] && [ "$trust" = "$proxy_ip" ]; then
  ok "$COMPOSE: server 는 proxy($proxy_ip) 만 신뢰"
else
  bad "$COMPOSE: FORWARDED_ALLOW_IPS($trust) ≠ proxy 주소($proxy_ip)"
fi

hits="$(grep -rnE -- '--forwarded-allow-ips"?,? *"?\*' server/Dockerfile docker-compose*.yml server/harness 2>/dev/null |
  grep -vE '^[^:]+:[0-9]+:[[:space:]]*#')"
if [ -n "$hits" ]; then
  bad "'--forwarded-allow-ips *' — 직접 닿는 누구든 IP 를 위조한다:"; echo "$hits" | sed 's/^/          /'
else
  ok "'--forwarded-allow-ips *' 없음"
fi

[ "$fail" -eq 0 ] && echo "OK: 프록시 설정 위반 없음" || echo "FAIL: 프록시 설정 위반"
exit "$fail"
