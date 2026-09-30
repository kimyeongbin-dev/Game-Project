"""
애플리케이션 설정 — 환경변수의 단일 진입점.

환경변수를 코드 곳곳에서 `os.getenv` 로 읽으면 기본값이 흩어지고,
어떤 값이 실제로 쓰이는지 추적하기 어려워진다. 여기 한 곳에서만 읽는다.

로컬·CI·배포가 동일한 설정 스키마를 쓰므로, 값이 빠지거나 형식이 틀리면
서버 기동 시점에 즉시 드러난다.
"""

from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


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
