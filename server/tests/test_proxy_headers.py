"""
프록시 신뢰 경계 (M4-1) — uvicorn 이 FORWARDED_ALLOW_IPS 로 정한 주소에서 온 X-Forwarded-For 만 믿는다

서버 앞의 Caddy 주소만 넣는다(docker-compose.yml). 이 테스트는 그 전제 — uvicorn 이 환경변수를 읽고, 다른 주소의 XFF 는
버리고, 미설정이면 아무것도 믿지 않는다 — 를 고정한다. 의존성(uvicorn) 버전을 올릴 때 동작이 바뀌면 여기서 잡힌다.
"""

import pytest
import uvicorn
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

PROXY = "172.30.0.10"


async def _client_seen(trusted_env, monkeypatch, peer: str, xff: str):
    if trusted_env is None:
        monkeypatch.delenv("FORWARDED_ALLOW_IPS", raising=False)
    else:
        monkeypatch.setenv("FORWARDED_ALLOW_IPS", trusted_env)
    seen = {}

    async def app(scope, receive, send):
        seen["client"] = scope["client"][0]

    config = uvicorn.Config(app, proxy_headers=True, log_config=None)   # 로깅 설정을 건드리지 않는다(마스킹 필터 보존)
    config.load()
    middleware = config.loaded_app
    while not isinstance(middleware, ProxyHeadersMiddleware):   # 래퍼를 벗겨 프록시 헤더 미들웨어를 찾는다
        middleware = middleware.app
    scope = {"type": "http", "client": (peer, 5000), "headers": [(b"x-forwarded-for", xff.encode())],
             "scheme": "http", "path": "/", "query_string": b""}
    await middleware(scope, None, None)
    return seen["client"]


async def test_forwarded_for_from_the_proxy_is_applied(monkeypatch):
    assert await _client_seen(PROXY, monkeypatch, PROXY, "203.0.113.7") == "203.0.113.7"


@pytest.mark.parametrize("peer", ["172.30.0.99", "203.0.113.50"])
async def test_forwarded_for_from_anyone_else_is_ignored(monkeypatch, peer):
    """같은 네트워크의 다른 컨테이너든 외부든 — 위조한 XFF 는 무시하고 접속 주소를 쓴다"""
    assert await _client_seen(PROXY, monkeypatch, peer, "198.51.100.1") == peer


async def test_unset_trusts_nothing_but_loopback(monkeypatch):
    """미설정 — uvicorn 기본 127.0.0.1. 프록시 주소에서 와도 믿지 않는다(fail-closed)"""
    assert await _client_seen(None, monkeypatch, PROXY, "198.51.100.1") == PROXY


async def test_spoofed_entries_before_the_proxy_hop_are_skipped(monkeypatch):
    """프록시가 덧붙인 값(맨 오른쪽)이 클라이언트다 — 클라이언트가 앞에 붙인 가짜 값은 쓰이지 않는다"""
    assert await _client_seen(PROXY, monkeypatch, PROXY, "198.51.100.1, 203.0.113.7") == "203.0.113.7"
