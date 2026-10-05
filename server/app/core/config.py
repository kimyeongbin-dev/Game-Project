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
    # 시간 체계 (maze.md §8·§9, M3 6단계) — 숫자만 운영 데이터로 조정한다
    # -----------------------------------------------------------------------
    # Fischer 게임 시계 — 초기값과 수락된 행동마다 더하는 증분
    clock_initial_ms: int = Field(default=300_000, ge=1)
    clock_increment_ms: int = Field(default=5_000, ge=0)
    # 접속 시계 — 게임당 누적 총량. 재접속해도 리셋하지 않는다
    connection_budget_ms: int = Field(default=60_000, ge=1)
    # 서버 유예(배포) — 두 시계를 멈추는 상한, 그리고 lifespan 종료 직전 몇 ms 안의 끊김을 배포로 볼지
    server_grace_max_ms: int = Field(default=30_000, ge=0)
    # 서버 유예 중 게임 시계 면제 상한 — 교체 공백(실측 ≈7 s) 근처. 재접속을 늦춰 생각하는 이득을 묶는다
    server_grace_game_ms: int = Field(default=8_000, ge=0)
    # 워커 하트비트가 이만큼 끊기면 그 워커가 가진 연결을 끊김으로 본다(크래시)
    worker_heartbeat_timeout_ms: int = Field(default=10_000, ge=100)
    server_grace_window_ms: int = Field(default=2_000, ge=0)
    # 데드라인 스위퍼 — 주기, 회차당 최대 처리 수, 클레임 리스(처리 전에 죽으면 이 시간 뒤 재등장)
    sweeper_interval_ms: int = Field(default=1_000, ge=10)
    sweeper_batch: int = Field(default=100, ge=1)
    sweeper_claim_lease_ms: int = Field(default=10_000, ge=100)
    # Redis 상태 유실 점검 — 주기, 그리고 생성 직후(DB 먼저 → Redis) 오탐을 피하는 최소 나이
    lost_scan_interval_sec: int = Field(default=30, ge=1)
    lost_game_min_age_sec: int = Field(default=30, ge=0)
    # Redis 장애 구간 — 이보다 짧으면 기록하지 않고, 이보다 길면 진행 중 게임을 무효로 닫는다
    store_outage_min_ms: int = Field(default=3_000, ge=0)
    store_outage_void_sec: int = Field(default=120, ge=1)
    # 기록한 장애 구간 보존 기간 (시계 정산에 쓰인다)
    outage_retention_sec: int = Field(default=86_400, ge=1)

    # -----------------------------------------------------------------------
    # 인증 (platform.md §1.3) — 이 서버는 access token 을 **검증만** 한다(발급은 인증 작업)
    # -----------------------------------------------------------------------
    # HS256 비밀키. 비어 있으면 모든 토큰을 거부한다(fail-closed). production 은 32자 이상 필수
    jwt_secret_key: str = ""
    # 허용 알고리즘은 이것 하나 — alg: none·알고리즘 바꿔치기를 막는다
    jwt_algorithm: Literal["HS256"] = "HS256"
    # MMR 초기값 (platform.md §4.2). MMR 저장소가 생기기 전 신원 조회의 임시값이다
    mmr_initial: int = Field(default=1000, ge=0)

    # -----------------------------------------------------------------------
    # 실시간 WS (maze.md §2·§12, M3 7단계)
    # -----------------------------------------------------------------------
    # connected 페이로드에 워커 id 를 싣는다 — 다중 워커 하네스 전용. 운영은 끈다
    ws_expose_worker: bool = False
    # 큐 대기자에게 queue_status 를 보내는 주기 (§3 "대기 중 주기적으로")
    queue_status_interval_sec: int = Field(default=5, ge=1)
    # WS ping — 반개방 끊김(신호 없이 사라진 연결)은 간격 + 타임아웃 + websockets close_timeout(10 s, uvicorn 미노출)
    # 뒤에야 감지된다(B2 파일럿 실측). 그 구간은 접속 시계에서 빠지므로 짧게 둔다: 최대 5 + 5 + 10 = 20 s (L19 한계)
    # Dockerfile prod CMD 의 --ws-ping-* 와 같아야 한다 — tests/test_dockerfile_flags.py 가 검사한다
    ws_ping_interval_sec: float = Field(default=5.0, gt=0)
    ws_ping_timeout_sec: float = Field(default=5.0, gt=0)
    # 메시지 하나의 상한(바이트). 클라이언트 메시지는 수십 바이트다 — 기본 16 MiB 는 남용 여지일 뿐이다
    ws_max_size_bytes: int = Field(default=4096, ge=256)
    # 끊김 기록이 실패(락 경합·Redis 장애)하면 원래 시각으로 이 시간까지 다시 시도한다 (검토 H4)
    disconnect_retry_max_sec: int = Field(default=120, ge=1)

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

    @model_validator(mode="after")
    def _production_needs_jwt_secret(self) -> "Settings":
        """비밀키가 비거나 짧으면 운영 서버가 모든 토큰을 거부하거나(빈 값) 위조에 약하다(짧은 값)"""
        if self.environment == "production" and len(self.jwt_secret_key) < 32:
            raise ValueError("JWT_SECRET_KEY must be at least 32 characters in production")
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
