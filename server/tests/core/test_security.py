"""access token 검증 (platform.md §1.3) — 무엇을 거부하는가가 핵심이다"""

import base64
import json
import time

import pytest

from app.core.config import Settings, settings
from app.core.security import AUTH_ANONYMOUS, AUTH_KAKAO, InvalidToken, verify_access_token
from tests.conftest import TEST_JWT_SECRET, mint_token


def _b64(data: dict) -> str:
    return base64.urlsafe_b64encode(json.dumps(data).encode()).rstrip(b"=").decode()


def test_valid_access_token(jwt_secret):
    claims = verify_access_token(mint_token(2210))
    assert claims.user_id == 2210
    assert claims.auth == AUTH_KAKAO
    assert not claims.is_anonymous


def test_anonymous_token_is_valid_but_marked(jwt_secret):
    """익명은 토큰으로서는 유효하다 — 멀티플레이 거부(4002)는 핸들러가 한다"""
    claims = verify_access_token(mint_token(7, auth=AUTH_ANONYMOUS))
    assert claims.is_anonymous


@pytest.mark.parametrize("token", [None, "", "not-a-jwt", "a.b.c"])
def test_missing_or_garbage(jwt_secret, token):
    with pytest.raises(InvalidToken):
        verify_access_token(token)


def test_refresh_token_rejected(jwt_secret):
    with pytest.raises(InvalidToken):
        verify_access_token(mint_token(1, typ="refresh"))


def test_expired_rejected(jwt_secret):
    with pytest.raises(InvalidToken):
        verify_access_token(mint_token(1, exp_offset_sec=-5))


def test_wrong_secret_rejected(jwt_secret):
    with pytest.raises(InvalidToken):
        verify_access_token(mint_token(1, secret="another-secret-0123456789abcdef!!"))


def test_alg_none_rejected(jwt_secret):
    now = int(time.time())
    token = ".".join([
        _b64({"alg": "none", "typ": "JWT"}),
        _b64({"sub": "1", "typ": "access", "auth": "kakao", "exp": now + 600}),
        "",
    ])
    with pytest.raises(InvalidToken):
        verify_access_token(token)


def test_other_hmac_algorithm_rejected(jwt_secret):
    """같은 비밀키라도 허용 목록 밖 알고리즘은 받지 않는다"""
    with pytest.raises(InvalidToken):
        verify_access_token(mint_token(1, algorithm="HS512"))


@pytest.mark.parametrize("sub", ["abc", "-3", "١٢", "1.5", ""])
def test_sub_must_be_ascii_user_id(jwt_secret, sub):
    from jose import jwt

    now = int(time.time())
    token = jwt.encode({"sub": sub, "typ": "access", "auth": "kakao", "exp": now + 600},
                       TEST_JWT_SECRET, algorithm="HS256")
    with pytest.raises(InvalidToken):
        verify_access_token(token)


def test_missing_exp_rejected(jwt_secret):
    from jose import jwt

    token = jwt.encode({"sub": "1", "typ": "access", "auth": "kakao"}, TEST_JWT_SECRET, algorithm="HS256")
    with pytest.raises(InvalidToken):
        verify_access_token(token)


def test_unknown_auth_type_rejected(jwt_secret):
    with pytest.raises(InvalidToken):
        verify_access_token(mint_token(1, auth="admin"))


def test_empty_secret_rejects_everything(monkeypatch):
    """비밀키가 없으면 fail-closed — 어떤 키로 서명한 토큰도 통과하지 못한다"""
    monkeypatch.setattr(settings, "jwt_secret_key", "")
    with pytest.raises(InvalidToken):
        verify_access_token(mint_token(1))


def test_production_requires_long_secret():
    from pydantic import ValidationError

    prod = {"_env_file": None, "environment": "production", "pubsub_namespace": "app"}
    with pytest.raises(ValidationError):
        Settings(**prod, jwt_secret_key="")
    with pytest.raises(ValidationError):
        Settings(**prod, jwt_secret_key="short")
    ok = Settings(**prod, jwt_secret_key="x" * 32)
    assert ok.jwt_algorithm == "HS256"
