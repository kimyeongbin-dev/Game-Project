"""
애플리케이션 설정 — 환경변수의 단일 진입점.

환경변수를 코드 곳곳에서 `os.getenv` 로 읽으면 기본값이 흩어지고,
어떤 값이 실제로 쓰이는지 추적하기 어려워진다. 여기 한 곳에서만 읽는다.

로컬·CI·배포가 동일한 설정 스키마를 쓰므로, 값이 빠지거나 형식이 틀리면
서버 기동 시점에 즉시 드러난다.
"""

from functools import lru_cache
from typing import Literal

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# 테스트 전용 Pub/Sub 네임스페이스 — tests/conftest.py 가 강제하고 production 은 거부한다
TEST_PUBSUB_NAMESPACE = "test"


class Settings(BaseSettings):
    """환경변수 기반 설정.

    필드명이 그대로 환경변수 이름이다 (대소문자 무시).
    예: `DATABASE_URL`, `REDIS_URL`, `DB_ENABLED`
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # -----------------------------------------------------------------------
    # 실행 환경
    # -----------------------------------------------------------------------
    environment: Literal["local", "ci", "production"] = "local"
    testing: bool = False

    # -----------------------------------------------------------------------
    # PostgreSQL — 유저 계정, 멀티 전적/MMR, 낱말 사전, 퍼즐 편지 메타데이터
    # -----------------------------------------------------------------------
    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/gamemoa"
    db_enabled: bool = True

    # -----------------------------------------------------------------------
    # Redis — 매치메이킹 큐, 실시간 방 상태, 턴 타이머, Pub/Sub
    # (PLATFORM_ARCHITECTURE.md §2.2)
    #
    # 논리 DB 를 용도별로 분리해 서로 간섭하지 않게 한다.
    #   0: 애플리케이션 상태 (큐 / 방 / 세션)
    #   1: 테스트 전용
    #   2: 레이트 리미터 카운터
    # -----------------------------------------------------------------------
    redis_url: str = "redis://localhost:6379/0"
    redis_enabled: bool = True
    redis_limiter_db: int = 2
    redis_socket_timeout: float = 5.0
    redis_socket_connect_timeout: float = 5.0
    redis_max_connections: int = 50

    # -----------------------------------------------------------------------
    # 멀티플레이 상태 (Redis 논리 DB 0) — 키 스키마는 app/db/redis_keys.py
    # -----------------------------------------------------------------------
    # 게임·매치·방 락 (SET NX PX). TTL 은 임계 구역 최대 길이보다 길어야 한다
    game_lock_ttl_ms: int = Field(default=5000, ge=100)
    # 락 대기 상한. 넘기면 GameBusy / LockTimeout
    game_lock_wait_ms: int = Field(default=2000, ge=0)
    # 종료된 게임 state·meta 보존 시간 — 재접속자가 game_end 를 받을 수 있게
    game_finished_ttl_sec: int = Field(default=300, ge=1)
    # 매칭 성사 후 ready 대기 기록의 안전망 TTL. 실제 기한 감지는 M3 6단계 스위퍼
    match_record_ttl_sec: int = Field(default=60, ge=1)
    # 친구 대전 방 TTL. 방이 바뀔 때마다 갱신한다
    room_ttl_sec: int = Field(default=3600, ge=1)
    # 매칭 MMR 범위 필터 (maze.md §3). Phase 1 은 끈다 — 큐 인구 확보 후 켠다
    match_mmr_filter_enabled: bool = False
    # Pub/Sub 구독이 끊겼을 때 재구독 대기 (지수 백오프 최소 → 최대). M3 4단계 app/ws/bus.py
    pubsub_reconnect_min_ms: int = Field(default=100, ge=1)
    pubsub_reconnect_max_ms: int = Field(default=5000, ge=1)
    # Pub/Sub 채널 네임스페이스 — 모든 이벤트 채널 이름의 접두어 `<ns>:`.
    # 채널은 논리 DB 와 무관한 Redis 서버 전역이라 DB 분리로는 격리되지 않는다. 그래서
    # 명시적으로 나눈다: 앱 = "app", 테스트 = "test" (docker-compose 의 server / server-test).
    # 테스트 픽스처는 "test" 가 아니면 중단하고, production 은 "test" 로 기동하지 않는다.
    pubsub_namespace: str = Field(default="app", pattern=r"^[a-z][a-z0-9_-]*$")

    # -----------------------------------------------------------------------
    # 레이트 리미팅
    # -----------------------------------------------------------------------
    rate_limit_enabled: bool = True
    rate_limit_per_minute: int = Field(default=60, ge=1)

    @property
    def redis_limiter_url(self) -> str:
        """레이트 리미터용 Redis URL.

        `redis_url` 의 논리 DB 번호만 `redis_limiter_db` 로 바꾼다.
        리미터 카운터가 애플리케이션 상태와 같은 DB 를 쓰면
        FLUSHDB 나 키 스캔이 서로를 건드린다.
        """
        base, _, _ = self.redis_url.rpartition("/")
        if not base:
            # DB 번호가 없는 형태 (redis://host:6379) — 그대로 뒤에 붙인다
            return f"{self.redis_url}/{self.redis_limiter_db}"
        return f"{base}/{self.redis_limiter_db}"

    @model_validator(mode="after")
    def _production_never_uses_test_channels(self) -> "Settings":
        """테스트 네임스페이스로 운영 서버가 뜨면 테스트 이벤트가 실제 소켓으로 간다"""
        if self.environment == "production" and self.pubsub_namespace == TEST_PUBSUB_NAMESPACE:
            raise ValueError("PUBSUB_NAMESPACE=test is not allowed in production")
        return self

    @property
    def is_production(self) -> bool:
        return self.environment == "production"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """설정 싱글톤.

    프로세스 수명 동안 한 번만 읽는다. 테스트에서 값을 바꿔야 하면
    `get_settings.cache_clear()` 를 호출한 뒤 환경변수를 조정한다.
    """
    return Settings()


settings = get_settings()
