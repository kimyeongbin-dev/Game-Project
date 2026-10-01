"""
유저 활동 — 유저당 하나의 활동(큐·매치·방·게임)을 Redis 키 하나로 보장한다.

"한 사용자는 동시에 하나의 큐에만 들어간다"(maze.md §3)와 방·큐 동시 참가 금지를
`user:{uid}:activity` 의 `SET NX` 하나로 원자적으로 지킨다. 전이(queue → match → game,
room → game)와 해제는 기대값 비교(CAS)로만 한다 — 다른 경로가 이미 바꾼 값을 덮지 않는다.
재접속 시 진행 중 게임을 찾는 색인도 이 키다(7단계).
"""

from typing import Optional

from redis.asyncio import Redis

from app.db import redis_keys as keys
from app.db.redis_lock import store_errors

# 활동 종류 → 이미 그 활동 중일 때의 §13 코드
_BUSY_CODES = {
    "queue": "already_in_queue",
    "match": "already_in_queue",   # 매칭 성사 후 ready 대기도 큐 흐름이다
    "room": "already_in_room",
    "game": "already_in_game",     # §13 에 추가한 코드 (M3 3단계)
}

# KEYS[1]=activity / ARGV[1]=기대값, ARGV[2]=새 값, ARGV[3]=EX 초('' 이면 없음)
_TRANSITION_LUA = """
if redis.call('GET', KEYS[1]) ~= ARGV[1] then
    return 0
end
if ARGV[3] == '' then
    redis.call('SET', KEYS[1], ARGV[2])
else
    redis.call('SET', KEYS[1], ARGV[2], 'EX', ARGV[3])
end
return 1
"""

_RELEASE_LUA = """
if redis.call('GET', KEYS[1]) == ARGV[1] then
    return redis.call('DEL', KEYS[1])
end
return 0
"""


class MultiplayerError(Exception):
    """§13 에러 코드를 가진 도메인 오류. 핸들러(7단계)가 code 를 그대로 보낸다"""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def busy_code(activity: str) -> str:
    """현재 활동 값 → 새 활동을 거절할 때의 §13 코드"""
    kind, _ = keys.parse_activity(activity)
    return _BUSY_CODES.get(kind, "already_in_game")


def _ex(ttl_sec: Optional[int]) -> str:
    return "" if ttl_sec is None else str(ttl_sec)


async def current(redis: Redis, user_id: int) -> Optional[str]:
    async with store_errors():
        return await redis.get(keys.user_activity(user_id))


async def claim(redis: Redis, user_id: int, value: str, *, ttl_sec: Optional[int] = None) -> None:
    """빈 상태에서만 활동을 잡는다. 이미 다른 활동이면 MultiplayerError(busy_code)

    같은 값이면 통과한다(같은 큐·방에 다시 들어오는 재요청).
    """
    async with store_errors():
        if await redis.set(keys.user_activity(user_id), value, nx=True, ex=ttl_sec):
            return
        existing = await redis.get(keys.user_activity(user_id))
    if existing == value:
        return
    if existing is None:  # 그 사이 풀렸다 — 한 번 더 시도
        return await claim(redis, user_id, value, ttl_sec=ttl_sec)
    raise MultiplayerError(busy_code(existing))


async def transition(
    redis: Redis, user_id: int, expected: str, new: str, *, ttl_sec: Optional[int] = None
) -> bool:
    """expected 일 때만 new 로 바꾼다. 바꿨으면 True. ttl_sec=None 이면 TTL 을 없앤다"""
    async with store_errors():
        changed = await redis.eval(
            _TRANSITION_LUA, 1, keys.user_activity(user_id), expected, new, _ex(ttl_sec)
        )
    return bool(changed)


async def release(redis: Redis, user_id: int, expected: str) -> bool:
    """expected 일 때만 해제한다. 해제했으면 True"""
    async with store_errors():
        released = await redis.eval(_RELEASE_LUA, 1, keys.user_activity(user_id), expected)
    return bool(released)
