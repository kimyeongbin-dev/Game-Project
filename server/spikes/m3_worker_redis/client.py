"""
M3 0단계 실측 클라이언트 — 운영 코드가 아니다.

사용 (compose.yml 의 spike-client 서비스 안에서):
    python client.py e1 [N]                    # 워커 분배 · 재접속 시 워커 동일 여부
    python client.py hold K SECONDS            # E2/E3: K 개 연결 유지, 끊김 이벤트 기록
    python client.py reconnect SECONDS         # E4: 끊기면 50ms 간격 재접속, 공백 측정
    python client.py e5 SECONDS [INTERVAL_MS]  # Pub/Sub 워커 간 지연 · 유실
    python client.py e6 GAMES ACTORS ACTIONS PAYLOAD_BYTES   # 게임별 락 + 상태 RMW 비용
    python client.py e7 SECONDS                # Redis 재시작 중 쓰기 결과 타임라인

시각은 모두 이 컨테이너의 time.time() 이다. 서버 로그와 같은 Docker VM 시계이므로
서로 비교할 수 있다. 결과는 JSON 한 줄씩 stdout 으로 낸다.
"""

import asyncio
import json
import os
import statistics
import sys
import time
import uuid
from collections import Counter

from websockets.asyncio.client import connect
from websockets.exceptions import ConnectionClosed

URL = os.environ.get("SPIKE_WS_URL", "ws://spike-server:8000/ws")


def out(event: str, **kw) -> None:
    print(json.dumps({"t": time.time(), "event": event, **kw}), flush=True)


def pct(values: list[float], p: float) -> float:
    if not values:
        return float("nan")
    s = sorted(values)
    return s[min(len(s) - 1, int(round(p / 100 * (len(s) - 1))))]


def close_info(exc: ConnectionClosed) -> dict:
    rcvd = exc.rcvd
    return {"code": rcvd.code if rcvd else None, "reason": rcvd.reason if rcvd else None,
            "rcvd_then_sent": exc.rcvd_then_sent}


async def hello(ws) -> int:
    return json.loads(await ws.recv())["pid"]


# ----------------------------------------------------------------------------- E1
async def e1(n: int) -> None:
    seq = []
    for _ in range(n):
        async with connect(URL) as ws:
            seq.append(await hello(ws))
    same = sum(1 for a, b in zip(seq, seq[1:]) if a == b)
    out("e1_sequential", n=n, dist=Counter(seq), same_as_previous=same, pairs=n - 1)

    conns = [await connect(URL) for _ in range(n)]
    pids = [await hello(ws) for ws in conns]
    out("e1_concurrent", n=n, dist=Counter(pids))
    for ws in conns:
        await ws.close()


# ----------------------------------------------------------------------------- E2/E3
async def _hold_one(i: int, deadline: float) -> None:
    try:
        async with connect(URL) as ws:
            pid = await hello(ws)
            out("hold_open", i=i, pid=pid)
            seq = 0
            while time.time() < deadline:
                await ws.send(json.dumps({"op": "echo", "seq": seq}))
                await asyncio.wait_for(ws.recv(), timeout=5)
                seq += 1
                await asyncio.sleep(0.5)
            out("hold_survived", i=i, pid=pid)
    except ConnectionClosed as exc:
        out("hold_closed", i=i, pid=locals().get("pid"), **close_info(exc))
    except Exception as exc:
        out("hold_error", i=i, pid=locals().get("pid"), error=repr(exc))


async def hold(k: int, seconds: float) -> None:
    deadline = time.time() + seconds
    await asyncio.gather(*(_hold_one(i, deadline) for i in range(k)))


# ----------------------------------------------------------------------------- E4
async def reconnect(seconds: float) -> None:
    deadline = time.time() + seconds
    gaps = []
    while time.time() < deadline:
        try:
            async with connect(URL, open_timeout=2) as ws:
                pid = await hello(ws)
                out("rc_connected", pid=pid)
                while time.time() < deadline:
                    await ws.send(json.dumps({"op": "echo"}))
                    await asyncio.wait_for(ws.recv(), timeout=5)
                    await asyncio.sleep(0.1)
                return
        except ConnectionClosed as exc:
            t_close = time.time()
            out("rc_closed", **close_info(exc))
        except Exception as exc:
            t_close = time.time()
            out("rc_error_on_connect", error=repr(exc))
        # 재접속 루프: 성공(hello 수신)까지 50ms 간격
        attempts = 0
        while time.time() < deadline:
            attempts += 1
            try:
                ws = await connect(URL, open_timeout=1)
                pid = await asyncio.wait_for(hello(ws), timeout=1)
                gap = (time.time() - t_close) * 1000
                gaps.append(gap)
                out("rc_reconnected", gap_ms=round(gap), attempts=attempts, pid=pid)
                await ws.close()
                break
            except Exception:
                await asyncio.sleep(0.05)
    out("rc_summary", gaps_ms=[round(g) for g in gaps])


# ----------------------------------------------------------------------------- E5
async def _connect_distinct() -> tuple:
    a = await connect(URL)
    pa = await hello(a)
    for _ in range(50):
        b = await connect(URL)
        pb = await hello(b)
        if pb != pa:
            return a, pa, b, pb
        await b.close()
    raise RuntimeError("서로 다른 워커에 붙지 못했다")


async def e5(seconds: float, interval_ms: float) -> None:
    sender, ps, receiver, pr = await _connect_distinct()
    out("e5_pair", sender_pid=ps, receiver_pid=pr)
    sent = 0
    got: dict[int, float] = {}
    dup = 0
    stop = time.time() + seconds

    async def recv_loop():
        nonlocal dup
        while True:
            try:
                m = json.loads(await asyncio.wait_for(receiver.recv(), timeout=3))
            except asyncio.TimeoutError:
                return
            if m.get("kind") != "bus":
                continue
            if m["seq"] in got:
                dup += 1
            got[m["seq"]] = (time.time() - m["sent"]) * 1000

    async def drain_sender():  # 송신자 워커도 같은 메시지를 받는다 — 버퍼만 비운다
        while True:
            try:
                await sender.recv()
            except Exception:
                return

    rt = asyncio.create_task(recv_loop())
    dt = asyncio.create_task(drain_sender())
    while time.time() < stop:
        await sender.send(json.dumps({"op": "publish", "seq": sent, "sent": time.time()}))
        sent += 1
        await asyncio.sleep(interval_ms / 1000)
    await rt
    dt.cancel()
    missing = sorted(set(range(sent)) - set(got))
    lat = list(got.values())
    # 유실 구간을 연속 범위로 압축해 보여준다
    ranges, start = [], None
    for i, s in enumerate(missing):
        if start is None:
            start = s
        if i + 1 == len(missing) or missing[i + 1] != s + 1:
            ranges.append([start, s])
            start = None
    out("e5_summary", sent=sent, received=len(got), lost=len(missing), lost_ranges=ranges, dup=dup,
        p50_ms=round(pct(lat, 50), 2), p99_ms=round(pct(lat, 99), 2), max_ms=round(max(lat), 2) if lat else None)
    await sender.close()
    await receiver.close()


# ----------------------------------------------------------------------------- E6
RELEASE = "if redis.call('get', KEYS[1]) == ARGV[1] then return redis.call('del', KEYS[1]) else return 0 end"


async def e6(games: int, actors: int, actions: int, payload_bytes: int) -> None:
    from redis.asyncio import Redis

    r = Redis.from_url(os.environ["REDIS_URL"], decode_responses=True)
    await r.flushdb()
    release = r.register_script(RELEASE)
    for g in range(games):
        await r.set(f"game:{g}:state", json.dumps({"n": 0, "pad": "x" * payload_bytes}))

    lat: list[float] = []
    lock_wait: list[float] = []

    async def actor(g: int) -> None:
        for _ in range(actions):
            t0 = time.perf_counter()
            token = uuid.uuid4().hex
            while not await r.set(f"game:{g}:lock", token, nx=True, px=2000):
                await asyncio.sleep(0.002)
            t1 = time.perf_counter()
            state = json.loads(await r.get(f"game:{g}:state"))
            state["n"] += 1
            await r.set(f"game:{g}:state", json.dumps(state))
            await release(keys=[f"game:{g}:lock"], args=[token])
            lat.append((time.perf_counter() - t0) * 1000)
            lock_wait.append((t1 - t0) * 1000)

    t = time.perf_counter()
    await asyncio.gather(*(actor(g) for g in range(games) for _ in range(actors)))
    wall = time.perf_counter() - t
    finals = [json.loads(await r.get(f"game:{g}:state"))["n"] for g in range(games)]
    out("e6_summary", games=games, actors=actors, actions=actions, payload_bytes=payload_bytes,
        correct=all(n == actors * actions for n in finals), expected=actors * actions,
        finals_min=min(finals), finals_max=max(finals),
        p50_ms=round(pct(lat, 50), 3), p99_ms=round(pct(lat, 99), 3), max_ms=round(max(lat), 3),
        lock_wait_p99_ms=round(pct(lock_wait, 99), 3),
        throughput_ops=round(len(lat) / wall), mean_ms=round(statistics.mean(lat), 3))
    await r.aclose()


# ----------------------------------------------------------------------------- E7
async def e7(seconds: float) -> None:
    deadline = time.time() + seconds
    ok = fail = 0
    last_state = None
    async with connect(URL) as ws:
        out("e7_pid", pid=await hello(ws))
        seq = 0
        while time.time() < deadline:
            await ws.send(json.dumps({"op": "redis_write", "seq": seq}))
            while True:
                m = json.loads(await ws.recv())
                if m.get("kind") == "redis_write":
                    break
            state = (m["ok"], m["available"], m.get("err", "")[:60] if not m["ok"] else "")
            if state != last_state:
                out("e7_transition", seq=seq, ok=m["ok"], available=m["available"], err=m.get("err"),
                    ms=round(m["ms"], 1), value=m.get("value"))
                last_state = state
            ok += m["ok"]
            fail += not m["ok"]
            seq += 1
            await asyncio.sleep(0.1)
        await ws.send(json.dumps({"op": "redis_get"}))
        while True:
            m = json.loads(await ws.recv())
            if m.get("kind") == "redis_get":
                break
    out("e7_summary", writes_ok=ok, writes_failed=fail, counter_after=m.get("value"), get_ok=m["ok"])


def main() -> None:
    cmd, *args = sys.argv[1:]
    if cmd == "e1":
        asyncio.run(e1(int(args[0]) if args else 100))
    elif cmd == "hold":
        asyncio.run(hold(int(args[0]), float(args[1])))
    elif cmd == "reconnect":
        asyncio.run(reconnect(float(args[0])))
    elif cmd == "e5":
        asyncio.run(e5(float(args[0]), float(args[1]) if len(args) > 1 else 10))
    elif cmd == "e6":
        asyncio.run(e6(*map(int, args)))
    elif cmd == "e7":
        asyncio.run(e7(float(args[0])))
    else:
        raise SystemExit(f"unknown command: {cmd}")


if __name__ == "__main__":
    main()
