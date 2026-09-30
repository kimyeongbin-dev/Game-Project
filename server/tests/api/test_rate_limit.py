"""
레이트 리미터 동작 검증.

배선이 실제로 살아있는지, 그리고 커스텀 429 응답이 쓰이는지를 고정한다.

배선은 조용히 깨질 수 있는 지점이 여러 개다:
  - `app.state.limiter` 미설정 -> 미들웨어가 AttributeError
  - 예외 핸들러 미등록 -> slowapi 기본 응답
  - 핸들러를 async def 로 정의 -> 미들웨어가 조용히 기본 핸들러로 대체
  - 미들웨어 미등록 -> 제한이 아예 걸리지 않음
이 테스트들은 그 각각을 관측 가능한 응답으로 확인한다.
"""

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.main import app
from app.middleware.rate_limiter import limiter, rate_limit_exceeded_handler


@pytest.fixture
def limited_client():
    """리미터를 켠 상태의 테스트 클라이언트.

    테스트 환경에서는 `settings.testing` 때문에 리미터가 기본 비활성이다.
    리미터 자체를 검증하려면 명시적으로 켜고, 카운터를 초기화해야 한다
    (카운터가 Redis 에 남아 테스트 간 간섭을 일으킨다).
    """
    previous = limiter.enabled
    limiter.enabled = True
    limiter.reset()
    try:
        with TestClient(app) as client:
            yield client
    finally:
        limiter.enabled = previous
        limiter.reset()


class TestRateLimitWiring:
    """배선 자체가 살아있는지"""

    def test_limiter_registered_on_app_state(self):
        """slowapi 는 app.state.limiter 를 규약으로 참조한다"""
        assert getattr(app.state, "limiter", None) is limiter

    def test_exception_handler_registered(self):
        """커스텀 핸들러가 RateLimitExceeded 에 등록되어 있어야 한다"""
        from slowapi.errors import RateLimitExceeded

        assert app.exception_handlers.get(RateLimitExceeded) is rate_limit_exceeded_handler

    def test_handler_must_be_synchronous(self):
        """핸들러가 async 면 미들웨어가 조용히 기본 핸들러로 대체한다.

        slowapi/middleware.py 의 sync_check_limits 가
        `inspect.iscoroutinefunction` 으로 검사해 교체하므로,
        async def 로 바뀌면 커스텀 응답이 전혀 쓰이지 않는다.
        """
        import inspect

        assert not inspect.iscoroutinefunction(rate_limit_exceeded_handler)

    def test_middleware_registered(self):
        """SlowAPIMiddleware 가 미들웨어 스택에 있어야 한다"""
        from app.middleware.rate_limiter import RateLimitMiddleware

        assert any(m.cls is RateLimitMiddleware for m in app.user_middleware)


class TestRateLimitEnforcement:
    """실제로 제한이 걸리는지"""

    def test_allows_requests_under_limit(self, limited_client):
        """제한 이하에서는 통과"""
        for _ in range(5):
            assert limited_client.get("/").status_code == 200

    def test_blocks_requests_over_limit(self, limited_client):
        """제한 초과 시 429 를 반환한다"""
        limit = settings.rate_limit_per_minute

        for i in range(limit):
            response = limited_client.get("/")
            assert response.status_code == 200, f"{i + 1}번째 요청이 제한 이하인데 차단됨"

        blocked = limited_client.get("/")
        assert blocked.status_code == 429

    def test_uses_custom_error_response(self, limited_client):
        """커스텀 429 본문과 Retry-After 헤더가 적용되어야 한다.

        slowapi 기본 응답은 {"error": "Rate limit exceeded: ..."} 형태이고
        Retry-After 헤더가 없다. 이 단정이 그 회귀를 잡는다.
        """
        for _ in range(settings.rate_limit_per_minute):
            limited_client.get("/")

        blocked = limited_client.get("/")
        assert blocked.status_code == 429

        body = blocked.json()
        assert body["success"] is False
        assert body["error"] == "rate_limit_exceeded"
        assert "요청이 너무 많습니다" in body["message"]
        assert "retry_after" in body
        assert blocked.headers.get("Retry-After") is not None


class TestRateLimitDisabled:
    """비활성 시 동작"""

    def test_disabled_limiter_does_not_block(self):
        """리미터가 꺼져 있으면 제한을 넘겨도 통과한다"""
        previous = limiter.enabled
        limiter.enabled = False
        limiter.reset()
        try:
            with TestClient(app) as client:
                for _ in range(settings.rate_limit_per_minute + 5):
                    assert client.get("/").status_code == 200
        finally:
            limiter.enabled = previous
            limiter.reset()


class TestRateLimitStorage:
    """카운터가 Redis 에 저장되는지 (워커 간 공유의 전제)"""

    def test_storage_is_redis_when_enabled(self):
        """Redis 활성 시 저장소가 RedisStorage 여야 한다.

        메모리 저장소로 강등되면 워커마다 따로 카운트해
        실효 제한이 워커 수만큼 곱해진다 (§2.2 위반).
        """
        if not settings.redis_enabled:
            pytest.skip("REDIS_ENABLED=false — 메모리 강등이 정상 동작")

        assert type(limiter._storage).__name__ == "RedisStorage"

    def test_limiter_url_uses_dedicated_logical_db(self):
        """리미터는 앱 상태와 다른 논리 DB 를 써야 한다"""
        assert settings.redis_limiter_url.endswith(f"/{settings.redis_limiter_db}")
