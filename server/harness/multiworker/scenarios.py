"""
M3 7단계 C — 실제 워커 2개 + 실제 Redis 장애 완료 판정 (판정 기준은 계획서 "C — 실제 다중 워커 하네스" 표, 측정 전 고정)

    python scenarios.py all --runs 3          # S5d(125 s 장애)는 --with-long 일 때 1회만
    python scenarios.py s3 s8 --runs 1        # 일부만

회차마다 results/run-<n>.json. 실패는 숨기지 않는다 — 시나리오가 예외로 끝나도 기록하고 다음으로 간다.
"""

import argparse
import asyncio
import json
import os
import re
import time
import traceback
from pathlib import Path

from harness import (
    Client, Docker, Pool, clocks, db_status, friend_game, health_by_worker, legal_move, raw_ws_handshake,
    redis, seat_clock, seed_users, token, wait_server,
)

PING_DETECT_MAX_SEC = 5 + 5 + 10 + 1     # 간격 + 타임아웃 + websockets close 대기 + 여유 (L19 한계, 사용자 결정)
HEARTBEAT_DETECT_MAX_SEC = 12            # worker_heartbeat_timeout 10 s + 스위퍼 주기
CLAIM_LUA = """
local due = redis.call('ZRANGEBYSCORE', KEYS[1], '-inf', ARGV[1], 'LIMIT', 0, tonumber(ARGV[3]))
for _, m in ipairs(due) do
    redis.call('ZADD', KEYS[1], 'XX', ARGV[2], m)
end
return due
"""

docker = Docker()


class Result:
    def __init__(self, name: str):
        self.name, self.failures, self.metrics, self.t0 = name, [], {}, time.monotonic()

    def check(self, cond, message: str) -> bool:
        if not cond:
            self.failures.append(message)
        return bool(cond)

    def to_dict(self) -> dict:
        return {"scenario": self.name, "ok": not self.failures, "failures": self.failures,
                "metrics": self.metrics, "elapsed_sec": round(time.monotonic() - self.t0, 2)}


async def redis_ms() -> int:
    r = redis()
    try:
        sec, usec = await r.time()
        return sec * 1000 + usec // 1000
    finally:
        await r.aclose()


async def move_current(players, res: Result, *, retry_busy_sec: float = 0.0) -> dict:
    """현재 좌석이 유효한 한 칸 이동 → 전원이 game_state·turn_change 를 같은 version 으로 받는다"""
    current = next(p for p in players if p.seat_no == players[0].turn["current_seat_no"])
    row, col = legal_move(current.view)
    deadline = time.monotonic() + retry_busy_sec
    while True:
        seq = await current.send("move", {"row": row, "col": col})
        got = await current.take(lambda m: m.get("ack_seq") == seq or (
            m["type"] == "turn_change" and (m["payload"].get("last_action") or {}).get("seat_no") == current.seat_no),
            timeout=8)
        if got["type"] == "turn_change":
            current._pending.insert(0, got)
            break
        if got["payload"].get("error") == "server_busy" and time.monotonic() < deadline:
            await asyncio.sleep(0.2)
            continue
        raise AssertionError(f"move refused: {got['payload']}")
    versions = set()
    for p in players:
        st = await p.recv("game_state", timeout=8)
        tc = await p.recv("turn_change", timeout=8)
        res.check(st["version"] == tc["version"], f"version split {st['version']}/{tc['version']}")
        res.check(tc["payload"]["last_action"] == {"seat_no": current.seat_no, "kind": "move"},
                  f"last_action {tc['payload']['last_action']}")
        res.check(st["payload"]["me"]["seat_no"] == p.seat_no, "game_state for another seat")
        p.view, p.turn = st["payload"], tc["payload"]
        versions.add(tc["version"])
    res.check(len(versions) == 1, f"seats saw different versions {versions}")
    return players[0].turn


def leak_check(players, res: Result) -> None:
    for p in players:
        end_at = next((i for i, m in enumerate(p.received) if m["type"] == "game_end"), len(p.received))
        before = p.received[:end_at]
        text = json.dumps(before)
        res.check("full_board" not in text, f"seat {p.seat_no}: full_board before game_end")
        res.check("spectator" not in text, f"seat {p.seat_no}: spectator packet for a ranked/no-spectate game")
        res.check("user_id\": " not in json.dumps([m for m in before if m["type"] != "connected"]),
                  f"seat {p.seat_no}: user_id on the wire")
        versions = [m["version"] for m in p.received if "version" in m]
        res.check(versions == sorted(versions), f"seat {p.seat_no}: version went backwards {versions}")
        ends = [m for m in p.received if m["type"] == "game_end"]
        res.check(len(ends) <= 1, f"seat {p.seat_no}: {len(ends)} game_end")


# ----- S1 좌석별 내용 -----

async def s1(pool: Pool, mode: str = "duel") -> Result:
    res = Result(f"s1_{mode}")
    counts = [1, 1] if mode == "duel" else [2, 1]
    a, b = await pool.on_workers(counts)
    players = [a[0], b[0], *a[1:]]
    await friend_game(players, mode)
    res.metrics["workers"] = sorted({p.worker for p in players})
    moves = 0
    for _ in range(20):
        await move_current(players, res)
        moves += 1
    for p in players[1:]:
        await p.send("surrender")
    for p in players:
        end = await p.recv("game_end", timeout=10)
        res.check(end["payload"]["reason"] == "last_standing", f"reason {end['payload']['reason']}")
        res.check(bool(end["payload"]["full_board"]), "game_end without full_board")
    for p in players:
        await p.drain(1.0)
        turns = [m for m in p.received if m["type"] == "turn_change" and m["payload"]["last_action"]]
        res.check(len(turns) == moves, f"seat {p.seat_no}: {len(turns)} turn_change for {moves} moves")
    leak_check(players, res)
    res.metrics["moves"] = moves
    return res


# ----- S2 한 워커의 구독만 끊기 -----

async def s2(pool: Pool) -> Result:
    res = Result("s2_bus_kill")
    (host,), (guest,) = await pool.on_workers([1, 1])
    created = await host.reply(await host.send("create_room", {"mode": "duel"}))
    await guest.reply(await guest.send("join_room", {"room_code": created["payload"]["room_code"]}))
    await host.recv("player_joined")
    before = await health_by_worker()
    res.check(set(before) >= {host.worker, guest.worker}, f"health saw {list(before)}")
    r = redis()
    try:
        target = before[host.worker]["bus"]["name"]
        ids = [c["id"] for c in await r.client_list() if c.get("name") == target]
        res.check(len(ids) == 1, f"bus connections named {target}: {len(ids)}")
        await r.client_kill_filter(_id=ids[0])
    finally:
        await r.aclose()
    t = time.monotonic()
    resynced = await host.recv("room_joined", timeout=5)
    res.metrics["resync_after_sec"] = round(resynced["_t"] - t, 3)
    other = [m for m in await guest.drain(3.0) if m["type"] == "room_joined"]
    res.check(not other, "the other worker's socket was resynced too")
    after = await health_by_worker()
    res.check(after[host.worker]["bus"]["resubscribes"] == before[host.worker]["bus"]["resubscribes"] + 1,
              "killed worker did not resubscribe exactly once")
    res.check(after[guest.worker]["bus"]["resubscribes"] == before[guest.worker]["bus"]["resubscribes"],
              "untouched worker resubscribed")
    return res


# ----- S3 워커 kill -9 -----

async def s3(pool: Pool) -> Result:
    res = Result("s3_worker_kill")
    (pa,), (pb,) = await pool.on_workers([1, 1])
    players = [pa, pb]
    game_id = await friend_game(players, "duel")
    await move_current(players, res)                       # 이제 B(좌석 2) 차례
    before = pa.view
    t_kill = time.monotonic()
    await docker.kill_pid(pa.pid)
    await move_current_alive(pb, res)                      # 살아 있는 워커의 좌석은 계속 둔다
    res.metrics["alive_move_after_kill_sec"] = round(time.monotonic() - t_kill, 3)
    again = None
    for _ in range(40):
        try:
            again = await Client(pa.user_id).open()
            break
        except Exception:
            await asyncio.sleep(0.25)
    res.check(again is not None, "could not reconnect after kill")
    if again:
        pool.clients.append(again)
        res.check(again.connected["payload"].get("reconnect") == {"game_id": game_id, "seat_no": 1},
                  f"reconnect {again.connected['payload'].get('reconnect')}")
        view = (await again.recv("game_state"))["payload"]
        res.check(view["turn_count"] == 2 and view["me"]["position"] == before["me"]["position"],
                  "state not restored")
        seen = {(e["row"], e["col"], e["orientation"]) for e in view["discovered_edges"]}
        res.check(seen >= {(e["row"], e["col"], e["orientation"]) for e in before["discovered_edges"]},
                  "discovered map shrank")
    await wait_server()

    # 재접속하지 않으면 — 크래시 워커의 좌석은 하트비트 끊김 뒤 끊김, 예산 뒤 기권패
    (qa,), (qb,) = await pool.on_workers([1, 1])
    players = [qa, qb]
    await friend_game(players, "duel")
    await move_current(players, res)
    await move_current(players, res)                       # 다시 A(좌석 1) 차례 — A 는 이제 죽는다
    t_kill = time.monotonic()
    await docker.kill_pid(qa.pid)
    left = await qb.recv("player_left", timeout=HEARTBEAT_DETECT_MAX_SEC + 5, state="reconnecting")
    res.metrics["dead_seat_detected_sec"] = round(left["_t"] - t_kill, 2)
    res.check(left["_t"] - t_kill <= HEARTBEAT_DETECT_MAX_SEC, "dead worker's seat detected too late")
    gone = await qb.recv("player_left", timeout=15, state="eliminated")
    res.check(gone["payload"]["reason"] == "disconnect_forfeit", f"reason {gone['payload']['reason']}")
    await qb.recv("game_end", timeout=5)
    extra = [m for m in await qb.drain(2.0) if m["type"] == "player_left" and m["payload"]["state"] == "eliminated"]
    res.check(not extra, "forfeit announced twice")
    await wait_server()
    return res


async def move_current_alive(p: Client, res: Result) -> None:
    row, col = legal_move(p.view)
    await p.send("move", {"row": row, "col": col})
    st = await p.recv("game_state", timeout=8)
    tc = await p.recv("turn_change", timeout=8)
    res.check(tc["payload"]["last_action"] == {"seat_no": p.seat_no, "kind": "move"}, "alive seat move lost")
    p.view, p.turn = st["payload"], tc["payload"]


# ----- S4 스위퍼 정확히 한 번 -----

async def s4(pool: Pool, variant: str = "plain", games: int = 20) -> Result:
    res = Result(f"s4_sweeper_{variant}")
    clients = await pool.any(games * 2)
    pairs = [clients[i:i + 2] for i in range(0, len(clients), 2)]
    game_ids = await asyncio.gather(*(friend_game(p, "duel") for p in pairs))
    t_start = time.monotonic()
    initial = pairs[0][0].turn["clocks"][0]["remaining_ms"] / 1000
    killed_pid = None
    if variant == "claim":
        r = redis()
        try:
            claimed = set()
            while time.monotonic() - t_start < initial + 1.5:   # 기한 직후의 클레임을 전부 가로챈다(클레임 후 사망 모사)
                now = await redis_ms()
                claimed |= set(await r.eval(CLAIM_LUA, 1, "deadlines:maze_1p", now, now + 10_000, 1000))
                await asyncio.sleep(0.02)
            res.metrics["stolen_claims"] = len(claimed)
        finally:
            await r.aclose()
    elif variant == "kill":
        await asyncio.sleep(max(0, initial - 0.2 - (time.monotonic() - t_start)))
        killed_pid = clients[0].pid
        await docker.kill_pid(killed_pid)
    deadline_sec = initial + (10 + 3 if variant == "claim" else 3) + (HEARTBEAT_DETECT_MAX_SEC if variant == "kill" else 0)
    ends = []
    for pair in pairs:
        for c in pair:
            if killed_pid is not None and c.pid == killed_pid:
                continue
            try:
                ends.append(await c.recv("game_end", timeout=max(1, deadline_sec - (time.monotonic() - t_start))))
            except Exception:
                res.check(False, f"no game_end for a seat within {deadline_sec:.0f}s")
    res.metrics["last_end_sec"] = round(max((e["_t"] for e in ends), default=t_start) - t_start, 2)
    for pair in pairs:
        for c in pair:
            if killed_pid is not None and c.pid == killed_pid:
                continue
            await c.drain(0.3)
            forfeits = [m for m in c.received if m["type"] == "player_left" and m["payload"]["state"] == "eliminated"]
            res.check(len(forfeits) == 1 and forfeits[0]["payload"]["reason"] == "time_forfeit",
                      f"{len(forfeits)} eliminations seen")
    r = redis()
    try:
        for gid in game_ids:
            raw = await r.get(f"game:{gid}:state")
            state = json.loads(raw) if raw else None
            res.check(state is not None and state["end_reason"] == "last_standing", f"{gid} not ended")
            if state:
                outs = [s for s in state["seats"] if s["elimination_reason"]]
                res.check(len(outs) == 1, f"{gid}: {len(outs)} seats eliminated")
    finally:
        await r.aclose()
    if killed_pid:
        await wait_server()
    return res


# ----- S5 실제 Redis 장애 -----

async def outage_count() -> int:
    r = redis()
    try:
        return await r.zcard("store:outages")
    finally:
        await r.aclose()


async def s5(pool: Pool, long: bool = False) -> Result:
    res = Result("s5_redis" + ("_long" if long else ""))
    if long:
        cs = await pool.any(4)
        gids = [await friend_game(cs[:2], "duel"), await friend_game(cs[2:], "duel")]
        await docker.action("redis", "pause")
        await asyncio.sleep(125)
        await docker.action("redis", "unpause")
        for c in cs:
            end = await c.recv("game_end", timeout=20)
            res.check(end["payload"]["reason"] == "server_fault", f"reason {end['payload']['reason']}")
            res.check(end["payload"]["full_board"] is not None, "voided game without full_board")
        for gid in gids:
            res.check(await db_status(gid) == "void", f"{gid} db status {await db_status(gid)}")
        return res

    (pa,), (pb,) = await pool.on_workers([1, 1])
    players = [pa, pb]
    await friend_game(players, "duel")
    base = await outage_count()
    r = redis()
    try:
        kills = await r.client_kill_filter(_type="normal", skipme=True)
    finally:
        await r.aclose()
    res.metrics["killed_normal_clients"] = kills
    t = time.monotonic()
    await move_current(players, res, retry_busy_sec=2.0)
    res.metrics["recover_after_client_kill_sec"] = round(time.monotonic() - t, 3)

    t = time.monotonic()
    await docker.action("redis", "restart", t=10)
    await move_current(players, res, retry_busy_sec=10.0)
    res.metrics["recover_after_restart_sec"] = round(time.monotonic() - t, 3)
    await asyncio.sleep(2)
    res.metrics["outages_after_restart"] = await outage_count() - base
    res.check(await outage_count() == base, "short restart recorded as an outage")

    current = next(p for p in players if p.seat_no == pa.turn["current_seat_no"])
    r0 = next(c["remaining_ms"] for c in current.turn["clocks"] if c["seat_no"] == current.seat_no)
    t_turn = current.received[-1]["_t"]
    await docker.action("redis", "pause")
    t_pause = time.monotonic()
    await asyncio.sleep(10)
    await docker.action("redis", "unpause")
    paused = time.monotonic() - t_pause
    await asyncio.sleep(2.5)
    res.check(await outage_count() == base + 1, f"outages recorded: {await outage_count() - base}")
    t_send = time.monotonic()
    await move_current(players, res, retry_busy_sec=5.0)
    after = next(c["remaining_ms"] for c in players[0].turn["clocks"] if c["seat_no"] == current.seat_no)
    expected = r0 - (t_send - t_turn - paused) * 1000 + 2000
    res.metrics["clock_error_ms"] = round(after - expected)
    res.check(abs(after - expected) <= 1500, f"outage not exempt: remaining {after} vs expected {expected:.0f}")
    return res


# ----- S6 SIGTERM 서버 유예 / SIGKILL 대조군 -----

async def s6(pool: Pool, signal_kind: str = "term") -> Result:
    res = Result(f"s6_{signal_kind}")
    cs = await pool.any(2)
    gid = await friend_game(cs, "duel")
    before = await clocks(gid)
    t = time.monotonic()
    if signal_kind == "term":
        await docker.action("server", "stop", t=30)
    else:
        await docker.action("server", "kill")
    codes = [await c.wait_closed(10) for c in cs]
    res.metrics["close_codes"] = codes
    if signal_kind == "term":
        res.check(all(code == 1012 for code in codes), f"close codes {codes}")
    await docker.action("server", "start")
    await wait_server()
    await asyncio.sleep(max(0, (15 if signal_kind == "kill" else 5) - (time.monotonic() - t)))
    res.metrics["downtime_sec"] = round(time.monotonic() - t, 2)
    again = [await Client(c.user_id).open() for c in cs]
    pool.clients.extend(again)
    for c in again:
        await c.recv("game_state", timeout=8)
    after = await clocks(gid)
    if signal_kind == "term":
        for c in cs:
            spent = seat_clock(before, c.seat_no)["conn_remaining_ms"] - seat_clock(after, c.seat_no)["conn_remaining_ms"]
            res.metrics[f"seat{c.seat_no}_connection_spent_ms"] = spent
            res.check(spent <= 1000, f"seat {c.seat_no} lost {spent} ms of connection clock across a deploy")
        logs = await docker.logs("server")
        raw = [t for c in cs if (t := token(c.user_id)[:20]) in logs]
        res.check(not re.search(r"token=ey", logs), "raw token in server logs")
        res.metrics["raw_token_hits"] = len(raw)
    else:  # 크래시는 면제가 없다 — 예산 5 s 보다 길게 끊겼으니 기권패
        state = json.loads(await (r := redis()).get(f"game:{gid}:state") or "null")
        await r.aclose()
        reasons = [s["elimination_reason"] for s in (state or {}).get("seats", [])]
        res.metrics["reasons"] = reasons
        res.check("disconnect_forfeit" in reasons, f"crash was exempted: {reasons}")
    return res


# ----- S7 반개방 -----

async def s7(pool: Pool) -> Result:
    res = Result("s7_half_open")
    cs = await pool.any(2)
    gid = await friend_game(cs, "duel")
    url = os.environ["SERVER_WS"].removeprefix("ws://")
    host, rest = url.split(":", 1)
    port, path = rest.split("/", 1)
    t_silent = time.monotonic()
    sock = raw_ws_handshake(host, int(port), f"/{path}?token={token(cs[1].user_id)}")  # 같은 계정 — 정상 연결은 4000
    try:
        detected = None
        while time.monotonic() - t_silent < PING_DETECT_MAX_SEC + 10:
            raw = await clocks(gid)
            if raw and seat_clock(raw, 2)["disconnected_at_ms"] is not None:
                detected = time.monotonic() - t_silent
                break
            await asyncio.sleep(0.25)
        res.metrics["detected_after_sec"] = None if detected is None else round(detected, 2)
        res.check(detected is not None and detected <= PING_DETECT_MAX_SEC,
                  f"half-open detected after {detected}")
    finally:
        sock.close()
    return res


# ----- S8 같은 계정을 다른 워커로 -----

async def s8(pool: Pool) -> Result:
    res = Result("s8_cross_worker_replace")
    (pa,), (pb,) = await pool.on_workers([1, 1])
    gid = await friend_game([pa, pb], "duel")
    old = pb
    newer = None
    for _ in range(15):
        c = await Client(pb.user_id).open()
        pool.clients.append(c)
        if c.worker != pb.worker:
            newer = c
            break
        old = c                                           # 같은 워커에 붙었다 — 그 워커가 이전 것을 닫았다
    if not res.check(newer is not None, "never landed on the other worker"):
        return res
    t = time.monotonic()
    code = await old.wait_closed(3)
    res.metrics["old_closed_after_sec"] = round(time.monotonic() - t, 3)
    res.check(code == 4000, f"old connection close code {code}")
    noise = [m for m in await pa.drain(2.0) if m["type"] == "player_left"]
    res.check(not noise, "replacement announced as a disconnect")
    raw = await clocks(gid)
    res.check(seat_clock(raw, 2)["disconnected_at_ms"] is None, "replacement charged the connection clock")
    return res


# ----- S9 연타 -----

async def s9(pool: Pool) -> Result:
    res = Result("s9_flood")
    cs = await pool.any(2)
    await friend_game(cs, "duel")
    first, second = cs

    async def flood():
        try:
            for _ in range(500):
                await second.send("move", {"row": 0, "col": 0})
        except Exception:
            pass

    task = asyncio.create_task(flood())
    await asyncio.sleep(0.05)
    r0 = next(c["remaining_ms"] for c in first.turn["clocks"] if c["seat_no"] == 1)
    t_turn = first.received[-1]["_t"]
    row, col = legal_move(first.view)
    t = time.monotonic()
    await first.send("move", {"row": row, "col": col})
    tc = await first.recv("turn_change", timeout=5)
    res.metrics["move_rtt_ms_under_flood"] = round((tc["_t"] - t) * 1000, 1)
    res.check((tc["_t"] - t) * 1000 <= 50, "move slowed down under flood")
    after = next(c["remaining_ms"] for c in tc["payload"]["clocks"] if c["seat_no"] == 1)
    expected = r0 - (t - t_turn) * 1000 + 2000
    res.metrics["clock_error_ms"] = round(after - expected)
    res.check(abs(after - expected) <= 200, f"flood cost the mover {expected - after:.0f} ms")
    await task
    # 서버는 1008 을 곧바로 보내고 처리를 멈추지만, 연타로 쌓인 미수신 메시지 때문에 websockets 가 클라이언트의 close 응답을
    # 읽지 못해 close_timeout(10 s) 뒤에 TCP 를 닫는다(파일럿 실측) — 그래서 15 s 를 기다린다
    code = await second.wait_closed(15)
    limited = [m for m in second.received if m.get("payload", {}).get("error") == "rate_limit_exceeded"]
    res.metrics["rate_limited"] = len(limited)
    res.check(limited and code == 1008, f"flood not stopped: {len(limited)} limited, close {code}")

    flooder = pool.free.pop()
    codes = []
    for _ in range(30):
        try:
            c = await Client(flooder).open()
            await c.close()
            codes.append("ok")
        except Exception:
            codes.append("closed")
    res.metrics["connects"] = {"ok": codes.count("ok"), "refused": codes.count("closed")}
    res.check(codes.count("ok") == 20 and codes[20:] == ["closed"] * 10, f"connect flood {codes}")
    return res


SCENARIOS = {
    "s1": lambda p: s1(p, "duel"), "s1t": lambda p: s1(p, "trio"), "s2": s2, "s3": s3,
    "s4": lambda p: s4(p, "plain"), "s4c": lambda p: s4(p, "claim"), "s4k": lambda p: s4(p, "kill"),
    "s5": s5, "s6": lambda p: s6(p, "term"), "s6k": lambda p: s6(p, "kill"), "s7": s7, "s8": s8, "s9": s9,
}


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("names", nargs="+")
    ap.add_argument("--runs", type=int, default=1)
    ap.add_argument("--with-long", action="store_true")
    args = ap.parse_args()
    names = list(SCENARIOS) if args.names == ["all"] else args.names
    await wait_server()
    out = Path("results")
    out.mkdir(exist_ok=True)
    for run in range(1, args.runs + 1):
        results = []
        for name in names:
            pool = Pool(await seed_users(80, f"r{run}{name}"))
            try:
                res = await SCENARIOS[name](pool)
            except Exception as exc:
                res = Result(name)
                res.failures.append(f"crashed: {exc!r}")
                res.metrics["traceback"] = traceback.format_exc()[-2000:]
            finally:
                await pool.close_all()
            results.append(res.to_dict())
            print(json.dumps(res.to_dict(), ensure_ascii=False)[:600], flush=True)
        if args.with_long and run == 1:
            pool = Pool(await seed_users(10, f"r{run}long"))
            try:
                res = await s5(pool, long=True)
            except Exception as exc:
                res = Result("s5_redis_long")
                res.failures.append(f"crashed: {exc!r}")
            await pool.close_all()
            results.append(res.to_dict())
            print(json.dumps(res.to_dict(), ensure_ascii=False)[:600], flush=True)
        (out / f"run-{run}.json").write_text(json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"== run {run}: {sum(r['ok'] for r in results)}/{len(results)} ok", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
