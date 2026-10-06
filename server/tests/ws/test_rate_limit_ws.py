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


def test_violations_are_forgotten_after_calm():
    """오래 유지된 정상 연결이 가끔의 초과를 누적해 1008 로 닫히지 않는다(독립 검토 #1 R14-6)"""
    clock = Tick()
    bucket = TokenBucket(3, 1.0, clock)
    for _ in range(3):
        bucket.allow()
    assert not bucket.allow() and bucket.violations == 1
    clock.t += 10                                              # 버스트를 다 채울 만큼 조용했다
    assert bucket.allow() and bucket.violations == 0


async def test_connect_limiter_key_always_has_ttl(redis):
    from app.db import redis_keys as keys
    from app.ws.rate_limit import ConnectLimiter

    # 전역 연결(app.db.redis)은 스레드 서버가 쓰고 있다 — 따로 연 클라이언트를 주입한다(테스트는 리미터 DB = 앱 DB 1)
    assert await ConnectLimiter(lambda: redis).allow(4_242)
    assert 0 < await redis.ttl(keys.ws_connect_rate(4_242)) <= 60


async def test_connect_flood_is_cut_before_identity_lookup(server, redis, monkeypatch):
    """리미터는 신원 조회(DB) 앞이다 — 연타가 DB 쿼리를 만들지 않는다(R11)"""
    monkeypatch.setattr(settings, "ws_connect_per_minute", 2)
    identity = server.handler.identity
    seen = []
    original = identity.lookup

    async def counting(uid):
        seen.append(uid)
        return await original(uid)

    monkeypatch.setattr(identity, "lookup", counting)
    for _ in range(5):
        c = await Client(server, 970).open(mint_token(970), expect_connected=False)
        await c.close()
    assert seen.count(970) == 2


# ----- M4-1 IP 별 접속 리밋 — 토큰 검증 전 -----

async def test_ip_flood_is_cut_before_the_token_is_even_checked(server, redis, monkeypatch):
    """무효 토큰 연타 — 한도 안에서는 4001, 넘으면 토큰을 보지 않고 1013. 유효 토큰도 같은 IP 면 막힌다"""
    import app.ws.maze_handler as handler_module
    monkeypatch.setattr(settings, "ws_connect_per_minute_ip", 3)
    checked = []
    real_verify = handler_module.verify_access_token

    def counting_verify(token):
        checked.append(token)
        return real_verify(token)

    monkeypatch.setattr(handler_module, "verify_access_token", counting_verify)
    codes = []
    for _ in range(5):
        c = await Client(server, 1).open("garbage", expect_connected=False)
        codes.append(await c.closed_code())
    assert codes == [4001, 4001, 4001, 1013, 1013]
    assert len(checked) == 3                                   # 넘은 접속은 서명 검증을 하지 않았다
    c = await Client(server, 7).open(mint_token(7), expect_connected=False)
    assert await c.closed_code() == 1013


async def test_ip_limit_is_independent_of_the_user_limit(redis, monkeypatch):
    """한도와 카운터가 따로다 — 유저 한도(작다)를 IP 에 쓰면 NAT 뒤 여럿이 막히고, 한 카운터를 나눠 쓰면 서로를 깎는다"""
    from app.db import redis_keys as keys
    from app.ws.rate_limit import ConnectLimiter

    monkeypatch.setattr(settings, "ws_connect_per_minute", 1)
    monkeypatch.setattr(settings, "ws_connect_per_minute_ip", 3)
    limiter = ConnectLimiter(lambda: redis)
    assert [await limiter.allow_ip("203.0.113.9") for _ in range(4)] == [True, True, True, False]
    assert await limiter.allow(4_243) and not await limiter.allow(4_243)   # 유저 한도 1 — IP 카운터와 무관
    assert 0 < await redis.ttl(keys.ws_connect_ip_rate("203.0.113.9")) <= 60


async def test_ip_limiter_fails_open_when_the_store_is_down():
    from redis.exceptions import ConnectionError
    from app.ws.rate_limit import ConnectLimiter

    class Down:
        def pipeline(self, **kw):
            raise ConnectionError("down")

    assert await ConnectLimiter(lambda: Down()).allow_ip("203.0.113.9")
    assert await ConnectLimiter(lambda: None).allow_ip("203.0.113.9")
