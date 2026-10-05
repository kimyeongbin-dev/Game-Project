"""
Access token 검증 (docs/api/platform.md §1.3, maze.md §2)

이 모듈은 **검증만** 한다. 발급(`/auth/anonymous`·`/auth/kakao`·`/auth/refresh`)은 인증 작업 몫이다(M3 7단계 사용자 결정).

- 알고리즘은 설정 하나(`jwt_algorithm`, HS256)만 받는다 — 목록에 하나만 두어 `alg: none`·알고리즘 바꿔치기를 막는다
- `typ` 이 `access` 가 아니면 거부한다. 리프레시 토큰을 access 자리에 쓰는 것을 막는다(§1.3)
- `exp`·`sub` 필수. `sub` 는 내부 user_id 의 문자열이다
- 비밀키가 비어 있으면 모든 토큰을 거부한다(fail-closed). production 은 기동 시 config 가 막는다
"""

from dataclasses import dataclass

from jose import JWTError, jwt

from app.core.config import settings

AUTH_ANONYMOUS = "anonymous"
AUTH_KAKAO = "kakao"
_AUTH_TYPES = frozenset({AUTH_ANONYMOUS, AUTH_KAKAO})


class InvalidToken(Exception):
    """토큰이 없거나 무효·만료·access 가 아니다. 사유는 서버 로그용이고 클라이언트에는 close 4001 만 간다"""


@dataclass(frozen=True)
class Claims:
    user_id: int
    auth: str

    @property
    def is_anonymous(self) -> bool:
        return self.auth == AUTH_ANONYMOUS


def verify_access_token(token: str | None) -> Claims:
    if not token:
        raise InvalidToken("missing")
    secret = settings.jwt_secret_key
    if not secret:
        raise InvalidToken("server has no JWT secret")
    try:
        data = jwt.decode(
            token,
            secret,
            algorithms=[settings.jwt_algorithm],
            options={"require_exp": True, "require_sub": True, "verify_aud": False},
        )
    except JWTError as exc:
        raise InvalidToken(type(exc).__name__) from None

    if data.get("typ") != "access":
        raise InvalidToken("not an access token")
    auth = data.get("auth")
    if auth not in _AUTH_TYPES:
        raise InvalidToken("unknown auth type")
    sub = data.get("sub")
    if not isinstance(sub, str) or not (sub.isascii() and sub.isdigit()):
        raise InvalidToken("sub is not a user id")
    return Claims(user_id=int(sub), auth=auth)
