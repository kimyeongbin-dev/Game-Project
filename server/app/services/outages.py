"""
Redis 장애 구간 — 시계 면제의 전역 입력 (maze.md §8, M3 6단계 판단 8 + 독립 검토 H1~H3)

장애 중에는 행동이 실패한다. 그 시간은 플레이어 탓이 아니므로 두 시계에서 뺀다.

**관측은 Redis 안의 전역 하트비트로 한다.** 워커마다 전용 루프(`sweeper._alive_loop`, 200 ms)와 스위퍼 회차가
`store:alive` 를 지금 시각으로 갱신한다(Lua 한 번). 직전 값과의 공백이 하한 이상이면 그 공백을 장애 구간으로 `store:outages` 에 적는다.

- 하트비트는 **어느 워커든** 성공하면 갱신된다. 공백 = 아무 워커도 Redis 에 쓰지 못한 구간 — Redis 전역 장애
  (또는 전 워커 정지). 워커 하나만 끊기면 다른 워커가 갱신하므로 공백이 생기지 않는다
- 마지막 성공 시각이 Redis 안에 있으므로 장애 중 재기동한 워커도 공백을 판정한다
- 정산하는 쪽은 기록된 구간에 더해 **지금 하트비트 공백**을 잠정 면제로 본다(`provisional`). 복구 직후 스위퍼가
  구간을 적기 전에 들어온 행동도 같은 면제를 받는다
- 기록과 하트비트 갱신이 Lua 한 번이라 여러 워커가 같은 공백을 두 번 적지 않는다
"""

from typing import Optional

from redis.asyncio import Redis

from app.core.config import settings
from app.db import redis_keys as keys
from app.db.redis_lock import store_errors
from app.services.maze_clock import Interval, merge

# KEYS[1]=alive, KEYS[2]=outages / ARGV[1]=now(음수면 Redis TIME), ARGV[2]=하한 ms, ARGV[3]=보존 ms
# 반환: 이번에 기록한 구간 {start, end} 또는 빈 목록
_HEARTBEAT_LUA = """
local now = tonumber(ARGV[1])
if now < 0 then
    local t = redis.call('TIME')
    now = tonumber(t[1]) * 1000 + math.floor(tonumber(t[2]) / 1000)
end
local last = tonumber(redis.call('GET', KEYS[1]) or '-1')
local out = {}
if last >= 0 and now - last >= tonumber(ARGV[2]) then
    redis.call('ZADD', KEYS[2], now, last .. '-' .. now)
    out = {last, now}
end
redis.call('ZREMRANGEBYSCORE', KEYS[2], '-inf', '(' .. (now - tonumber(ARGV[3])))
if now > last then
    redis.call('SET', KEYS[1], now)
end
return out
"""


def _parse(member: str) -> Interval:
    start, _, end = member.partition("-")
    return int(start), int(end)


def void_boundary(outage_start_ms: int) -> int:
    """긴 장애로 무효 처리할 게임의 시작 상한 (M3 7단계 다중 워커 실측)

    장애 시작은 마지막 하트비트로 추정한다. 실제 정지는 그 뒤 하트비트 간격 안에 일어난다 — 간격은 전용 루프 200 ms 지만
    그 루프가 실패 중이면 회차(1 s)로 물러나므로, 공백 하한 `store_outage_min_ms` 를 보수적 상한으로 쓴다(그보다 긴 공백은
    이미 장애다). 그 사이에 시작한 게임도 장애를 겪었다 — 실측에서 정지 0.7 s 전에 생긴
    게임이 126 s 장애에도 무효가 되지 않았다. 장애 중에는 게임을 만들 수 없고 복구 뒤 게임은 시작이 구간 끝(시작 + 120 s 이상)
    이후이므로, 이 경계가 복구 뒤 게임을 잘못 닫지 않는다(검토 M10).
    """
    return outage_start_ms + settings.store_outage_min_ms


async def heartbeat(redis: Redis, now_ms: int, *, min_ms: int, retention_ms: int) -> Optional[Interval]:
    """하트비트를 지금으로 갱신한다. 직전 하트비트와의 공백이 min_ms 이상이었으면 그 구간을 기록하고 돌려준다"""
    async with store_errors():
        out = await redis.eval(_HEARTBEAT_LUA, 2, keys.store_alive(), keys.store_outages(),
                               now_ms, min_ms, retention_ms)
    return (int(out[0]), int(out[1])) if out else None


async def beat(redis: Redis, *, min_ms: int, retention_ms: int) -> Optional[Interval]:
    """`heartbeat` 와 같되 시각은 스크립트 안의 Redis TIME — 왕복 한 번이고, 장애 중 걸려 있던 요청이 복구 순간에
    처리돼도 그 순간의 시각이 찍힌다(미리 읽은 시각이 낡지 않는다)"""
    return await heartbeat(redis, -1, min_ms=min_ms, retention_ms=retention_ms)


def provisional(alive_raw: Optional[str], now_ms: int, min_ms: int) -> list[Interval]:
    """아직 기록되지 않은 지금의 공백 — 하트비트가 min_ms 이상 멈춰 있으면 [마지막 하트비트, now)"""
    if alive_raw is None:
        return []
    last = int(alive_raw)
    return [(last, now_ms)] if now_ms - last >= min_ms else []


async def read(redis: Redis, since_ms: int) -> list[Interval]:
    """since_ms 이후에 끝난 기록된 장애 구간 (합집합)"""
    async with store_errors():
        members = await redis.zrangebyscore(keys.store_outages(), since_ms, "+inf")
    return merge(_parse(m) for m in members)
