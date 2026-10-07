"""
브라우저 오리진 허용 목록 — HTTP CORS 와 WebSocket 핸드셰이크가 같은 판정을 쓴다 (M4-1)

- 허용 목록은 `settings.cors_allowed_origins`. 비워 두면(None) 환경별 기본값: local·ci 는 `*`(개발 편의),
  **production 은 빈 목록**(브라우저 오리진 없음 — fail-closed). production 에 `*` 를 명시하면 기동을 거부한다(config validator)
- Starlette 의 CORS 미들웨어는 **WebSocket 에 적용되지 않는다** — WS 핸들러가 `origin_allowed` 로 직접 거른다
- 네이티브 앱(Android·iOS)은 `Origin` 을 보내지 않는다 — 헤더가 없으면 통과. 인증은 쿼리 bearer 토큰이라(쿠키 아님)
  교차 사이트 요청이 남의 자격을 실어 보낼 수 없다. Origin 대조는 그 위의 방어선이다
"""

from typing import Optional
from urllib.parse import urlsplit

from app.core.config import Settings, settings

WILDCARD = "*"


DEFAULT_PORTS = {"http": 80, "https": 443}


def normalize_origin(origin: str) -> str:
    """브라우저가 보내는 형태로 — 소문자 scheme·host, 기본 포트·끝 '/' 없음. 설정 목록도 이 형태로 바꿔 CORS 미들웨어(정확
    일치)와 WS 대조가 같은 판정을 하게 한다(M4-1 독립 검토)"""
    if origin == WILDCARD:
        return origin
    parts = urlsplit(origin.strip().rstrip("/"))
    if not parts.scheme or not parts.hostname:
        return origin.strip().rstrip("/")
    host = parts.hostname.lower()
    if ":" in host:
        host = f"[{host}]"
    port = parts.port
    netloc = host if port is None or DEFAULT_PORTS.get(parts.scheme.lower()) == port else f"{host}:{port}"
    return f"{parts.scheme.lower()}://{netloc}"


def allowed_origins(config: Settings = settings) -> list[str]:
    if config.cors_allowed_origins is not None:
        return list(dict.fromkeys(normalize_origin(o) for o in config.cors_allowed_origins))
    return [] if config.is_production else [WILDCARD]


def origin_allowed(origin: Optional[str], config: Settings = settings) -> bool:
    """WS 핸드셰이크의 Origin — 없으면(네이티브 앱) 허용, 있으면 정규화한 목록과 일치해야 한다"""
    if origin is None:
        return True
    allowed = allowed_origins(config)
    return WILDCARD in allowed or normalize_origin(origin) in allowed
