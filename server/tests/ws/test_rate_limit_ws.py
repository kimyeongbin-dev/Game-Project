"""
WS 레이트 리밋 (M3 7단계 판단 7 / 기준 B6)

토큰 버킷은 가짜 단조 시계로, 배선(초과 시 처리 안 함·1008·접속 1013)은 실서버로 본다.
"""

import pytest
import pytest_asyncio

from app.core.config import settings
from app.ws.rate_limit import TokenBucket
from tests.conftest import TEST_JWT_SECRET, mint_token
from tests.ws.live import Client, LiveServer, build_app, build_handler, purge, raw_redis
from tests.ws.test_maze_handler import FakeIdentity, start_ranked


class Tick:
    def __init__(self):
        self.t = 0.0

    def __call__(self) -> float:
        return self.t


# ----- 버킷 -----

def test_bucket_burst_then_refill():
    clock = Tick()
    bucket = TokenBucket(20, 5.0, clock)
    assert all(bucket.allow() for _ in range(20))
    assert not bucket.allow() and bucket.violations == 1
    clock.t += 1.0                       # 1 s → 5개 회복
    assert sum(bucket.allow() for _ in range(10)) == 5


def test_normal_pace_is_never_limited():
    """턴제 정상 페이스(1 msg/s)는 10분 동안 한 번도 걸리지 않는다"""
    clock = Tick()
    bucket = TokenBucket(settings.ws_msg_burst, settings.ws_msg_per_sec, clock)
    for _ in range(600):
        assert bucket.allow()
        clock.t += 1.0
    assert bucket.violations == 0


def test_burst_of_quick_actions_fits():
    """한 턴에 벽 거절 2회 + 이동 같은 짧은 연속은 버스트 안이다"""
    bucket = TokenBucket(settings.ws_msg_burst, settings.ws_msg_per_sec, Tick())
    assert all(bucket.allow() for _ in range(5))


# ----- 배선 (실서버) -----

class CountingGames:
    """핸들러가 게임 서비스를 몇 번 불렀나 — 리밋에 걸린 요청은 0회여야 한다"""

    def __init__(self, real):
        self.real, self.calls = real, 0

    async def move(self, *args, **kwargs):
        self.calls += 1
        return await self.real.move(*args, **kwargs)

    def __getattr__(self, name):
        return getattr(self.real, name)


@pytest.fixture(scope="module")
def server():
    old = settings.jwt_secret_key
    settings.jwt_secret_key = TEST_JWT_SECRET
    handler = build_handler(FakeIdentity(), bucket_factory=lambda: TokenBucket(3, 0.001))
    handler.games = CountingGames(handler.games)
    live = LiveServer(build_app(handler)).start()
    live.handler = handler
    yield live
    live.stop()
    settings.jwt_secret_key = old


@pytest_asyncio.fixture
async def redis(server):
    client = raw_redis()
    await purge(client)
    yield client
    await purge(client)
    await client.aclose()


@pytest_asyncio.fixture
async def clients(server, redis):
    opened = []

    async def make(*user_ids):
        out = [await Client(server, uid).open() for uid in user_ids]
        opened.extend(out)
        return out

    yield make
    for c in opened:
        await c.close()


async def test_over_limit_is_refused_without_touching_the_game(server, clients, monkeypatch):
    monkeypatch.setattr(settings, "ws_violation_close", 1_000)
    cs, _ = await start_ranked(clients, "duel", 2, base=900)   # join_queue·ready 가 버킷 2개를 썼다 — 남은 1개
    second = cs[1]                                             # 차례가 아닌 좌석의 연타
    before = server.handler.games.calls
    seqs = [await second.send("move", {"row": 1, "col": 4}) for _ in range(6)]
    replies = [await second.reply(s) for s in seqs]
    codes = [r["payload"]["error"] for r in replies]
    assert codes == ["not_your_turn"] + ["rate_limit_exceeded"] * 5
    assert server.handler.games.calls - before == 1            # 걸린 5건은 서비스에 닿지 않았다


async def test_persistent_abuse_closes_1008(clients, monkeypatch):
    monkeypatch.setattr(settings, "ws_violation_close", 5)
    [c] = await clients(950)
    for _ in range(3 + 5):
        await c.send("leave_queue")
    assert await c.closed_code() == 1008


async def test_connect_flood_closes_1013_before_anything(server, redis, monkeypatch):
    monkeypatch.setattr(settings, "ws_connect_per_minute", 3)
    for _ in range(3):
        c = await Client(server, 960).open()
        await c.close()
    late = await Client(server, 960).open(mint_token(960), expect_connected=False)
    assert await late.closed_code() == 1013
    assert late.received == []
    other = await Client(server, 961).open()                    # 유저 단위다 — 다른 유저는 영향 없다
    await other.close()
