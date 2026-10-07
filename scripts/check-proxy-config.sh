#!/usr/bin/env bash
# =============================================================================
# 프록시 신뢰 경계·토큰 로그 가드 (M4-1, 독립 검토 반영)
#
#   bash scripts/check-proxy-config.sh      # 위반이 있으면 exit 1
#
# 검사
#   1. Caddyfile: 사이트 `log` 지시어가 없다(전역 `log default` 만 허용) — URI 의 ?token= 이 접속 로그로 샌다(maze.md §2)
#   2. Caddyfile: 기본 로거가 request>uri 의 token 쿼리를 지운다 — 오류 로그(502)도 URI 를 남긴다
#   3. Caddyfile: admin off · auto_https off(TLS 는 엣지) · trusted_proxies 가 환경변수 · trusted_proxies_strict ·
#      업스트림이 환경변수 · XFF = {client_ip} 하나
#   4. 모든 compose(개발·운영 오버레이·하네스): server 가 호스트 포트·host 네트워크를 쓰지 않는다
#   5. 개발 compose: server 의 FORWARDED_ALLOW_IPS 기본값 = proxy 의 고정 주소 기본값
#   6. 어디에도 "모두 신뢰"가 없다 — FORWARDED_ALLOW_IPS·--forwarded-allow-ips 의 * · 0.0.0.0/0 · ::/0 (어떤 형태든),
#      CADDY_TRUSTED_PROXIES 의 0.0.0.0/0 · ::/0 · private_ranges
# =============================================================================
set -u
cd "$(dirname "$0")/.."

CADDYFILE=infra/caddy/Caddyfile
COMPOSE=docker-compose.yml
COMPOSES=(docker-compose.yml docker-compose.prod.yml server/harness/multiworker/compose.yml)
fail=0
bad() { echo "  FAIL  $*"; fail=1; }
ok() { echo "  OK    $*"; }

# 주석 줄을 뺀 Caddyfile 본문
body="$(grep -vE '^[[:space:]]*#' "$CADDYFILE")"

if grep -E '^[[:space:]]*log([[:space:]]|$|\{)' <<<"$body" | grep -qvE '^[[:space:]]*log[[:space:]]+default[[:space:]]*\{'; then
  bad "$CADDYFILE: 사이트 'log' 지시어 — 쿼리의 토큰이 접속 로그로 샌다(전역 'log default' 만 허용)"
else
  ok "$CADDYFILE: 사이트 접속 로그 없음"
fi
if tr -d '\n' <<<"$body" | grep -qE 'log[[:space:]]+default[[:space:]]*\{.*format[[:space:]]+filter.*request>uri[[:space:]]+query[[:space:]]*\{[[:space:]]*delete[[:space:]]+token'; then
  ok "$CADDYFILE: 기본 로거가 token 쿼리를 지운다(오류 로그 포함)"
else
  bad "$CADDYFILE: 기본 로거에 request>uri token 삭제 필터가 없다 — 502 오류 로그가 토큰을 남긴다"
fi
grep -qE '^[[:space:]]*admin[[:space:]]+off' <<<"$body" && ok "$CADDYFILE: admin off" || bad "$CADDYFILE: admin off 없음"
grep -qE '^[[:space:]]*auto_https[[:space:]]+off' <<<"$body" && ok "$CADDYFILE: auto_https off" || bad "$CADDYFILE: auto_https off 없음(TLS 는 엣지)"
grep -qF 'trusted_proxies static {$CADDY_TRUSTED_PROXIES' <<<"$body" && ok "$CADDYFILE: 신뢰 대역 = 환경변수" || bad "$CADDYFILE: trusted_proxies 가 환경변수가 아니다"
grep -qE '^[[:space:]]*trusted_proxies_strict[[:space:]]*$' <<<"$body" && ok "$CADDYFILE: trusted_proxies_strict" \
  || bad "$CADDYFILE: trusted_proxies_strict 없음 — 엣지가 덧붙인 XFF 의 맨 왼쪽(클라이언트가 보낸 값)을 쓴다"
grep -qF 'reverse_proxy {$CADDY_UPSTREAM' <<<"$body" && ok "$CADDYFILE: 업스트림 = 환경변수" || bad "$CADDYFILE: 업스트림이 환경변수가 아니다"
grep -qE 'header_up[[:space:]]+X-Forwarded-For[[:space:]]+\{client_ip\}' <<<"$body" && ok "$CADDYFILE: XFF = 판정한 클라이언트 하나" \
  || bad "$CADDYFILE: XFF 를 {client_ip} 로 다시 쓰지 않는다 — 배포에서 엣지 주소를 클라이언트로 본다"

# compose 의 서비스 블록(다음 2칸 들여쓰기 서비스 이름 전까지)
block() { awk -v name="$2" '$0 == "  " name ":" {on=1; next} on && /^  [a-z][a-z0-9_-]*:/{exit} on' "$1"; }

for f in "${COMPOSES[@]}"; do
  [ -f "$f" ] || continue
  server_block="$(block "$f" server)"
  if grep -qE '^    (ports:|network_mode:[[:space:]]*"?host)' <<<"$server_block"; then
    bad "$f: server 가 호스트 포트·host 네트워크를 쓴다 — proxy 를 우회한다"
  else
    ok "$f: server 호스트 포트 없음"
  fi
done

trust="$(block "$COMPOSE" server | grep -oE 'FORWARDED_ALLOW_IPS: *\$\{GAMEMOA_PROXY_IP:-[0-9.]+\}' | grep -oE '[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+')"
proxy_ip="$(block "$COMPOSE" proxy | grep -oE 'ipv4_address: *\$\{GAMEMOA_PROXY_IP:-[0-9.]+\}' | grep -oE '[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+')"
if [ -n "$trust" ] && [ "$trust" = "$proxy_ip" ]; then
  ok "$COMPOSE: server 는 proxy($proxy_ip) 만 신뢰"
else
  bad "$COMPOSE: FORWARDED_ALLOW_IPS($trust) ≠ proxy 주소($proxy_ip)"
fi

# "모두 신뢰" — 주석 줄은 뺀다
ALL='(\*|0\.0\.0\.0/0|::/0)'
targets=(server/Dockerfile "${COMPOSES[@]}" .env.example)
hits="$(grep -nHE -- "(FORWARDED_ALLOW_IPS[\"']?[[:space:]]*[:=][[:space:]]*[\"']?[^\"'#]*${ALL}|--forwarded-allow-ips[\"']?[[:space:]]*[,= ][[:space:]]*[\"']?${ALL})" "${targets[@]}" 2>/dev/null |
  grep -vE '^[^:]+:[0-9]+:[[:space:]]*#')"
if [ -n "$hits" ]; then
  bad "서버가 모든 주소의 XFF 를 믿는다 — 직접 닿는 누구든 IP 를 위조한다:"; echo "$hits" | sed 's/^/          /'
else
  ok "서버 '모두 신뢰' 없음(* · 0.0.0.0/0 · ::/0, 플래그·환경변수 모든 형태)"
fi
hits="$(grep -nHE -- "CADDY_TRUSTED_PROXIES[\"']?[[:space:]]*[:=][^#]*(0\.0\.0\.0/0|::/0|private_ranges)" "${COMPOSES[@]}" .env.example 2>/dev/null |
  grep -vE '^[^:]+:[0-9]+:[[:space:]]*#')"
if [ -n "$hits" ]; then
  bad "Caddy 가 너무 넓은 대역을 엣지로 믿는다 — 그 대역의 누구든 XFF 로 IP 를 위조한다:"; echo "$hits" | sed 's/^/          /'
else
  ok "Caddy 신뢰 대역에 0.0.0.0/0 · ::/0 · private_ranges 없음"
fi

[ "$fail" -eq 0 ] && echo "OK: 프록시 설정 위반 없음" || echo "FAIL: 프록시 설정 위반"
exit "$fail"
