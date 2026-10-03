"""시간 유틸 — 프로젝트 표준 UTC 시각과 멀티플레이 시계의 시각 출처."""

from datetime import datetime, timezone
from typing import Protocol


def utcnow() -> datetime:
    """timezone-naive UTC 현재 시각.

    datetime.utcnow() 는 Python 3.12+ 에서 deprecated 이며 제거 예정이다.
    다만 DB의 DateTime 컬럼과 to_dict() 의 isoformat() + "Z" 직렬화가
    naive UTC 를 전제하므로, tzinfo 를 떼어내 기존 동작을 그대로 유지한다.
    """
    return datetime.now(timezone.utc).replace(tzinfo=None)


class Clock(Protocol):
    """멀티플레이 시계의 시각 출처 (maze.md §8). epoch ms"""

    async def now_ms(self) -> int: ...


class RedisClock:
    """Redis `TIME` — 모든 워커가 같은 시계를 본다 (M3 6단계 판단 1)

    워커마다 벽시계를 읽으면 호스트가 다를 때(롤링 배포) 같은 게임의 차감이 처리한 워커에 따라
    달라진다. 클라이언트 시각은 어디에도 쓰지 않는다. 실패는 StoreUnavailable 로 올라간다.
    """

    async def now_ms(self) -> int:
        # 순환 import 방지 — app.db 가 app.core 를 import 한다
        from app.db.redis_lock import require_redis, store_errors

        redis = require_redis()
        async with store_errors():
            seconds, micros = await redis.time()
        return int(seconds) * 1000 + int(micros) // 1000


redis_clock = RedisClock()
