"""프록시 경유 E2E — 헬스, WS 업그레이드·close 코드 보존, X-Forwarded-For 위조 무시, CORS 프리플라이트 (M4-1)"""

import asyncio

import httpx
from websockets.asyncio.client import connect
from websockets.exceptions import ConnectionClosed


def test_health_through_the_proxy(base):
    r = httpx.get(f"{base}/health", timeout=5)
    assert r.status_code == 200 and r.json()["status"] == "healthy"


async def test_ws_upgrade_through_the_proxy_keeps_the_close_code(ws_base):
    """업그레이드 뒤 바이트 터널 — 서버의 4001 이 클라이언트까지 그대로 온다(Caddy 가 1006 으로 바꾸지 않는다)"""
    async with connect(f"{ws_base}/api/v1/ws/maze?token=garbage") as ws:
        try:
            await asyncio.wait_for(ws.recv(), 5)
        except ConnectionClosed as closed:
            assert closed.rcvd is not None and closed.rcvd.code == 4001
        else:
            raise AssertionError("expected close 4001")


def test_spoofed_forwarded_for_does_not_open_new_rate_limit_windows(base):
    """매 요청 다른 X-Forwarded-For 를 보내도 한 클라이언트다 — 위조가 통하면 요청마다 새 창이라 429 가 나오지 않는다.
    프록시 경유로 판별하는 것은 **Caddy 단**(신뢰 안 한 XFF 를 버린다)이다. 서버 단(FORWARDED_ALLOW_IPS = 프록시 주소만)은
    tests/test_proxy_headers.py 와 server 포트 비노출(scripts/check-proxy-config.sh)이 맡는다"""
    per_minute = httpx.get(f"{base}/health", timeout=5).json()["rate_limit"]["per_minute"]
    statuses = []
    with httpx.Client(timeout=5) as client:
        for i in range(per_minute + 1):
            r = client.get(f"{base}/", headers={"X-Forwarded-For": f"198.51.100.{i % 250 + 1}"})
            statuses.append(r.status_code)
            if r.status_code == 429:
                break
    assert 429 in statuses, f"no 429 after {len(statuses)} spoofed requests"


def test_cors_preflight_through_the_proxy(base):
    r = httpx.options(f"{base}/health", headers={"Origin": "https://x.example",
                                                 "Access-Control-Request-Method": "GET"}, timeout=5)
    assert r.status_code == 200
    assert r.headers.get("access-control-allow-origin") == "*"     # 개발 기본 — 운영 빈 목록은 하네스가 본다
    assert "access-control-allow-credentials" not in r.headers
