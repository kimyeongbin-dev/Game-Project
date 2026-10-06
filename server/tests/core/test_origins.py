"""
브라우저 오리진 (M4-1) — HTTP CORS 와 WS 핸드셰이크가 같은 목록. production 은 fail-closed
"""

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.core.origins import allowed_origins, origin_allowed

PROD = dict(_env_file=None, environment="production", pubsub_namespace="app", jwt_secret_key="x" * 32)


def test_defaults_per_environment():
    assert allowed_origins(Settings(_env_file=None, environment="local")) == ["*"]
    assert allowed_origins(Settings(_env_file=None, environment="ci")) == ["*"]
    assert allowed_origins(Settings(**PROD)) == []          # 아무 설정이 없어도 운영은 브라우저 오리진 없음


def test_production_refuses_every_origin():
    with pytest.raises(ValueError):
        Settings(**PROD, cors_allowed_origins=["https://ok.example", "*"])
    ok = Settings(**PROD, cors_allowed_origins=["https://ok.example"])
    assert allowed_origins(ok) == ["https://ok.example"]


def test_origins_from_environment_json(monkeypatch):
    monkeypatch.setenv("CORS_ALLOWED_ORIGINS", '["https://a.example", "https://b.example/"]')
    config = Settings(_env_file=None)
    assert origin_allowed("https://b.example", config) and origin_allowed("https://a.example/", config)
    assert not origin_allowed("https://evil.example", config)


def test_ws_origin_rule():
    prod = Settings(**PROD, cors_allowed_origins=["https://app.example"])
    assert origin_allowed(None, prod)                        # 네이티브 앱 — Origin 없음
    assert origin_allowed("https://app.example", prod)
    assert not origin_allowed("https://evil.example", prod)
    assert not origin_allowed("null", prod)                  # sandboxed iframe·file://
    assert not origin_allowed("https://app.example.evil.example", prod)
    assert not origin_allowed("https://evil.example", Settings(**PROD))   # 기본(빈 목록)
    assert origin_allowed("https://anything.example", Settings(_env_file=None))   # 개발 *


def test_cors_middleware_uses_the_list_without_credentials():
    """main.app 의 CORS 배선 — 개발 기본(*)에서 프리플라이트가 열리고 credentials 는 허용하지 않는다"""
    from app.main import app
    with TestClient(app) as client:
        r = client.options("/health", headers={"Origin": "https://x.example", "Access-Control-Request-Method": "GET"})
    assert r.status_code == 200
    assert r.headers.get("access-control-allow-origin") == "*"
    assert "access-control-allow-credentials" not in r.headers
