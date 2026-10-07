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
from typing import Optional

from harness import (
    Client, Docker, Pool, clocks, db_status, friend_game, health_by_worker, legal_move, raw_ws_handshake,
    redis, seat_clock, seed_users, token, wait_server, wait_two_workers,
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


async def resync_views(players, seconds: float = 1.5) -> None:
    """장애 뒤 — 버스 재구독 재동기화가 최신 화면을 보낸다. 받은 것 중 가장 최신으로 각자의 화면을 맞춘다"""
    for p in players:
        best: dict[str, tuple] = {}
        for m in await p.drain(seconds):   # 도착 순서가 아니라 가장 높은 (version, turn_count) 가 최신이다
            if m["type"] in ("game_state", "turn_change"):
                rank = (m.get("version", 0), m["payload"]["turn_count"])
                if m["type"] not in best or rank >= best[m["type"]][0]:
                    best[m["type"]] = (rank, m["payload"])
        if "game_state" in best:
            p.view = best["game_state"][1]
        if "turn_change" in best and best["turn_change"][1]["turn_count"] >= p.turn["turn_count"]:
            p.turn = best["turn_change"][1]


async def server_turn(players) -> int:
    r = redis()
    try:
        raw = await r.get(f"game:{players[0].view['game_id']}:state")
    finally:
        await r.aclose()
    return json.loads(raw)["turn_count"] if raw else -1


async def probe_fresh_connects(pool: Pool, stop: asyncio.Event, out: list, *, every: float = 0.25) -> None:
    """장애 중·직후 — 새 유저로 새 접속을 every 마다 시작한다(기다리지 않고 겹쳐서). (시작, 끝, 결과) 를 남긴다.
    같은 소켓의 요청은 차례로 처리돼, 장애 중 붙잡힌 요청이 있으면 그 소켓으로는 '복구 뒤 새 요청'을 잴 수 없다(M4-1 실측)"""
    async def one(user_id: int):
        started = time.monotonic()
        try:
            c = await Client(user_id).open()
            pool.clients.append(c)
            out.append((started, time.monotonic(), "connected"))
        except Exception as exc:
            out.append((started, time.monotonic(), type(exc).__name__))

    tasks = []
    while not stop.is_set() and pool.free:
        tasks.append(asyncio.create_task(one(pool.free.pop())))
        try:
            await asyncio.wait_for(stop.wait(), every)
        except asyncio.TimeoutError:
            pass
    await asyncio.gather(*tasks, return_exceptions=True)


async def move_until_accepted(players, attempts: list, *, deadline_sec: float = 15.0) -> None:
    """장애 중·직후 — 100 ms 마다 같은 이동을 보낸다. 응답을 기다리는 동안 다른 확인(하네스 자신의 Redis 조회)을 끼우지
    않는다: 그 대기가 끼면 재개 지연이 서버가 아니라 하네스 루프를 잰다(M4-1 실측 — 1.0~1.7 s 로 보였던 것이 그것이었다).
    attempts 에 (보낸 시각, 응답 시각, 결과) 를 남긴다. 결과 not_your_turn = 응답을 잃은 이전 시도가 이미 반영됐다"""
    current = next(p for p in players if p.seat_no == players[0].turn["current_seat_no"])
    expected = players[0].turn["turn_count"] + 1
    row, col = legal_move(current.view)
    end = time.monotonic() + deadline_sec

    def is_turn(m):
        return m["type"] == "turn_change" and m["payload"]["turn_count"] == expected

    while time.monotonic() < end:
        sent = time.monotonic()
        seq = await current.send("move", {"row": row, "col": col})
        try:
            got = await current.take(lambda m: m.get("ack_seq") == seq or is_turn(m), timeout=8)
        except Exception:
            attempts.append((sent, time.monotonic(), "timeout"))
            continue
        outcome = "turn" if is_turn(got) else got["payload"].get("error")
        attempts.append((sent, time.monotonic(), outcome))
        if outcome == "turn":
            current._pending.insert(0, got)
            return
        if outcome == "not_your_turn":
            return
        await asyncio.sleep(0.1)
    raise AssertionError(f"move never accepted: {attempts[-3:]}")


async def move_current(players, res: Result, *, retry_busy_sec: float = 0.0, strict: bool = True,
                       trace: Optional[list] = None) -> dict:
    """현재 좌석이 유효한 한 칸 이동 → 전원이 그 턴(turn_count+1)의 game_state·turn_change 를 받는다

    strict: 장애가 없는 시나리오 — 두 메시지가 같은 version 이어야 한다. 장애 뒤에는 재동기화가 같은 턴의 화면을 다른
    (더 최신) version 으로 또 보내므로 턴 번호로만 맞춘다.
    """
    current = next(p for p in players if p.seat_no == players[0].turn["current_seat_no"])
    expected = players[0].turn["turn_count"] + 1
    row, col = legal_move(current.view)
    deadline = time.monotonic() + retry_busy_sec

    def is_turn(m):
        return m["type"] == "turn_change" and m["payload"]["turn_count"] == expected

    while True:
        sent = time.monotonic()
        seq = await current.send("move", {"row": row, "col": col})
        got = await current.take(lambda m: m.get("ack_seq") == seq or is_turn(m), timeout=8)
        if trace is not None:   # 시도별 (보낸 시각, 응답 시각, 결과) — 재개 지연 분석용(M4-1)
            trace.append((sent, time.monotonic(), "turn" if is_turn(got) else got["payload"].get("error")))
        if is_turn(got):
            current._pending.insert(0, got)
            break
        if got["payload"].get("error") == "server_busy" and time.monotonic() < deadline:
            # server_busy 여도 반영됐을 수 있다(응답만 잃었다) — 서버 상태로 확인한다
            if await server_turn(players) >= expected:
                res.metrics["applied_despite_busy"] = res.metrics.get("applied_despite_busy", 0) + 1
                break
            await asyncio.sleep(0.2)
            continue
        r = redis()
        try:
            raw = await r.get(f"game:{players[0].view['game_id']}:state")
        finally:
            await r.aclose()
        st = json.loads(raw) if raw else {}
        ck = await clocks(players[0].view["game_id"])
        out = redis()
        try:
            outs = await out.zrange("store:outages", 0, -1, withscores=True)
            alive = await out.get("store:alive")
        finally:
            await out.aclose()
        raise AssertionError(f"move refused: {got['payload'].get('error')} — harness seat {current.seat_no} turn "
                             f"{expected - 1}, server current {st.get('current_seat_no')} turn {st.get('turn_count')} "
                             f"end {st.get('end_reason')} seats {[(x['seat_no'], x['elimination_reason']) for x in st.get('seats', [])]} "
                             f"clocks {json.dumps(ck)[:700]} outages {outs[-3:]} alive {alive} now {await redis_ms()}")
    for p in players:
        tc = await p.take(is_turn, timeout=8)
        st = await p.take(lambda m: m["type"] == "game_state" and m["payload"]["turn_count"] == expected, timeout=8)
        if strict:
            res.check(st["version"] == tc["version"], f"version split {st['version']}/{tc['version']}")
            res.check(tc["payload"]["last_action"] == {"seat_no": current.seat_no, "kind": "move"},
                      f"last_action {tc['payload']['last_action']}")
        res.check(st["payload"]["me"]["seat_no"] == p.seat_no, "game_state for another seat")
        p.view, p.turn = st["payload"], tc["payload"]
    return players[0].turn


async def vision_check(players, res: Result) -> None:
    """좌석별 화면의 누적 관측이 Redis 의 **그 좌석** vision 과 같다 — 다른 좌석의 기록을 보내지 않는다(독립 검토 #2 Q9, 관점 4)"""
    gid = players[0].view["game_id"]
    r = redis()
    try:
        for p in players:
            raw = json.loads(await r.get(f"game:{gid}:vision:{p.seat_no}"))
            stored = {(e[0], e[1], "horizontal" if e[2] == "h" else "vertical", e[3]) for e in raw["edges"]}
            shown = {(e["row"], e["col"], e["orientation"], e["wall"]) for e in p.view["discovered_edges"]}
            res.check(shown == stored, f"seat {p.seat_no}: discovered_edges differ from its own vision record")
            stored_seen = {(x["seat_no"], x["row"], x["col"], x["turn"]) for x in raw["last_seen"]}
            shown_seen = {(x["seat_no"], x["position"]["row"], x["position"]["col"], x["seen_at_turn"])
                          for x in p.view["last_seen_players"]}
            res.check(shown_seen == stored_seen, f"seat {p.seat_no}: last_seen_players differ from its own record")
            others = {o["seat_no"] for o in p.view["others"]}
            res.check(p.seat_no not in others and "position" not in json.dumps(p.view["others"]),
                      f"seat {p.seat_no}: others carry positions")
    finally:
        await r.aclose()
    res.metrics["vision_checked_seats"] = len(players)


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
    await vision_check(players, res)
    for p in players[1:]:
        await p.send("surrender")
    for p in players:
        end = await p.recv("game_end", timeout=10)
        res.check(end["payload"]["reason"] == "last_standing", f"reason {end['payload']['reason']}")
        res.check(bool(end["payload"]["full_board"]), "game_end without full_board")
    for p in players:
        await p.drain(1.0)
        turns = [m for m in p.received if m["type"] == "turn_change" and m["payload"]["last_action"]]
        # HARNESS_FALSIFY=1 — 하네스 판별력 확인: 틀린 기대값이면 이 시나리오가 반드시 실패해야 한다
        expected_turns = moves + (1 if os.environ.get("HARNESS_FALSIFY") else 0)
        res.check(len(turns) == expected_turns, f"seat {p.seat_no}: {len(turns)} turn_change for {expected_turns} moves")
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
    await wait_two_workers(pa.pid)

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
    gone = await qb.recv("player_left", timeout=40, state="eliminated")   # 접속 예산 30 s 뒤
    res.check(gone["payload"]["reason"] == "disconnect_forfeit", f"reason {gone['payload']['reason']}")
    await qb.recv("game_end", timeout=5)
    extra = [m for m in await qb.drain(2.0) if m["type"] == "player_left" and m["payload"]["state"] == "eliminated"]
    res.check(not extra, "forfeit announced twice")
    await wait_two_workers(qa.pid)
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
                # 진단 — 어느 워커의 어느 좌석이, 무엇을 마지막으로 받았나(M4-1: 20게임 중 한 좌석만 통지를 못 받았다)
                res.metrics.setdefault("missing", []).append({
                    "user": c.user_id, "worker": c.worker, "killed_pid": killed_pid, "seat": c.seat_no,
                    "game": c.view.get("game_id") if c.view else None,
                    "closed": c.ws.close_code if c.ws is not None else None,
                    "last": [m["type"] for m in c.received[-6:]]})
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
            state = None
            while True:   # 두 좌석 모두 죽은 워커에 있던 게임은 클라이언트로 못 본다 — 기한까지 상태를 본다(최소 한 번)
                raw = await r.get(f"game:{gid}:state")
                state = json.loads(raw) if raw else None
                if (state and state["end_reason"]) or time.monotonic() - t_start > deadline_sec + 2:
                    break
                await asyncio.sleep(0.25)
            res.check(state is not None and state["end_reason"] == "last_standing", f"{gid} not ended")
            if state:
                outs = [s for s in state["seats"] if s["elimination_reason"]]
                res.check(len(outs) == 1, f"{gid}: {len(outs)} seats eliminated")
    finally:
        await r.aclose()
    if killed_pid:
        await wait_two_workers(killed_pid)
    else:
        # 두 워커의 스위퍼가 모두 돌고 있었다 — 한쪽이 죽은 채 다른 쪽 혼자 처리한 "정확히 한 번"이 아니다(독립 검토 #2 Q9)
        seen = await health_by_worker()
        res.metrics["sweepers"] = {w: (rt["sweeper"]["running"], rt["sweeper"]["last_tick_ok"]) for w, rt in seen.items()}
        res.check(len(seen) == 2 and all(rt["sweeper"]["running"] and rt["sweeper"]["last_tick_ok"] for rt in seen.values()),
                  "both workers' sweepers must be running")
    return res


# ----- S5 실제 Redis 장애 -----

async def measure_downtime(limit_sec: float, recovered: Optional[list] = None) -> int:
    """Redis 가 PING 에 답하지 못한 가장 긴 구간(ms) — 서버의 기록과 독립적인 측정(재시도 없는 연결, 100 ms 간격)

    recovered: 주면 복구 순간(time.monotonic)을 덧붙인다 — 행동 재개 지연을 잰다(독립 검토 #3 높음 2)"""
    from redis.asyncio import Redis
    client = Redis.from_url(os.environ["REDIS_URL"], socket_timeout=0.5, socket_connect_timeout=0.5)
    down_since, longest = None, 0
    deadline = time.monotonic() + limit_sec
    try:
        while time.monotonic() < deadline:
            try:
                await client.ping()
                if down_since is not None:
                    longest = max(longest, int((time.monotonic() - down_since) * 1000))
                    down_since = None
                    if recovered is not None:
                        recovered.append(time.monotonic())
                    if longest:
                        break
            except Exception:
                if down_since is None:
                    down_since = time.monotonic()
                try:
                    await client.connection_pool.disconnect()
                except Exception:
                    pass
            await asyncio.sleep(0.1)
    finally:
        await client.aclose()
    return longest


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
    await move_current(players, res, retry_busy_sec=2.0, strict=False)
    await resync_views(players, 0.5)
    res.metrics["recover_after_client_kill_sec"] = round(time.monotonic() - t, 3)

    t = time.monotonic()
    recovered_at: list = []
    probe = asyncio.create_task(measure_downtime(30.0, recovered_at))   # 하네스가 공백을 직접 잰다(독립 검토 #2 Q4)
    await asyncio.sleep(0.3)
    fresh: list = []
    stop_fresh = asyncio.Event()
    fresh_task = asyncio.create_task(probe_fresh_connects(pool, stop_fresh, fresh))
    await docker.action("redis", "restart", t=10)
    attempts: list = []
    await move_until_accepted(players, attempts)
    await asyncio.sleep(1.5)                  # 복구 뒤 새 접속을 몇 번 더 본다
    stop_fresh.set()
    await fresh_task
    await resync_views(players, 2.0)
    res.metrics["recover_after_restart_sec"] = round(time.monotonic() - t, 3)
    await asyncio.sleep(2)
    # 재시작 공백이 하한(store_outage_min_ms 3 s) 미만이면 기록되지 않고, 이상이면 한 번 기록된다 — 공백을 재서 판정한다.
    # (계획서는 E7 의 ≈2 s 재시작을 전제로 "기록 없음"을 기준으로 적었다 — 이 하네스의 컨테이너 재시작은 더 길다)
    r = redis()
    try:
        recorded = await r.zrangebyscore("store:outages", "-inf", "+inf")
    finally:
        await r.aclose()
    new = recorded[base:]
    gaps = [int(m.split("-")[1]) - int(m.split("-")[0]) for m in new]
    downtime_ms = await probe
    res.metrics["restart_outages_ms"], res.metrics["restart_downtime_ms"] = gaps, downtime_ms
    # 장애 정의는 하트비트 전용 연결 기준이다(maze.md §8). 그보다 늦게 처리되는 만큼은 면제 없이 흐른다(독립 검토 #3 높음 2).
    # 둘을 나눠 잰다(2026-10-07 사용자 결정 — 기록하고 M4-2 에서 수정):
    # - 복구 뒤 시작한 새 접속(250 ms 간격) 중 첫 성공 / 장애 중 들어와 붙잡힌 행동이 처리된 시각
    # 둘 다 같은 원인(Redis 가 꺼진 동안 이름 조회 3.3 s + 기본 스레드 풀 포화 → 워커의 Redis 클라이언트마다 재접속이 늦다)으로
    # 복구 뒤 최대 ≈1.3 s 늦을 수 있다(M4-1 실측). 알려진 한계다 — 여기서는 퇴행만 잡는다(상한 2 s). 수정은 M4-2(앱 풀 주소 고정)
    if recovered_at:
        rec = recovered_at[0]
        rel = [(int((a - rec) * 1000), int((b - rec) * 1000), r) for a, b, r in attempts]
        res.metrics["attempts_vs_recovery_ms"] = rel
        accepted = [b for a, b, r in rel if r in ("turn", "not_your_turn")]
        res.metrics["held_action_done_after_recovery_ms"] = accepted[-1] if accepted else None
        fresh_rel = sorted((int((a - rec) * 1000), int((b - rec) * 1000), r) for a, b, r in fresh)
        ok_after = [b for a, b, r in fresh_rel if a >= 0 and r == "connected"]
        res.metrics["fresh_request_after_recovery_ms"] = ok_after[0] if ok_after else None
        res.metrics["fresh_probes"] = len(fresh_rel)
        res.check(bool(ok_after) and ok_after[0] <= 2_000,
                  f"a fresh request after recovery took {ok_after[0] if ok_after else None} ms")
        held = res.metrics["held_action_done_after_recovery_ms"]
        res.check(held is not None and held <= 2_000, f"a held action finished {held} ms after recovery")
    # 기록됐다면 그 길이가 직접 잰 공백에 붙어야 한다 — 기록은 마지막 성공 → 첫 성공, 공백은 첫 실패 → 첫 성공이라
    # 하트비트 간격(200 ms) + 탐침 간격(100 ms)만큼 길 수 있다(검토 #3 중간: 재시작 구간도 면제량을 본다)
    for gap in gaps:
        res.check(downtime_ms - 500 <= gap <= downtime_ms + 1_000, f"restart recorded {gap} ms for {downtime_ms} ms down")
    # 직접 잰 공백이 하한(3 s)보다 확실히 길면 정확히 한 건, 확실히 짧으면 0건 — 경계 근처(±0.5 s)는 어느 쪽도 허용
    if downtime_ms >= 3_500:
        res.check(len(new) == 1, f"restart down {downtime_ms} ms but outage records {gaps}")
    elif downtime_ms <= 2_500:
        res.check(len(new) == 0, f"restart down {downtime_ms} ms but outage records {gaps}")
    else:
        res.check(len(new) <= 1, f"restart outage records {gaps}")
    base = await outage_count()
    state = json.loads(await (rr := redis()).get(f"game:{players[0].view['game_id']}:state"))
    await rr.aclose()
    res.check(not any(x["elimination_reason"] for x in state["seats"]), "a seat was eliminated across the restart")

    current = next(p for p in players if p.seat_no == pa.turn["current_seat_no"])
    gid = players[0].view["game_id"]
    await docker.action("redis", "pause")
    t_pause = time.monotonic()
    await asyncio.sleep(10)
    await docker.action("redis", "unpause")
    paused = time.monotonic() - t_pause
    await resync_views(players, 2.5)
    res.check(await outage_count() == base + 1, f"outages recorded: {await outage_count() - base}")
    # 기대값은 서버의 정산식 그대로 — 차례 시작 시 잔량 − (보낸 시각 − 차례 시작 − 기록된 장애 구간과의 겹침) + 증분.
    # 겹침은 이번 정지만이 아니다: 장애 끝은 복구 뒤 첫 하트비트라(1 s 주기) 직전 재시작 구간이 이 차례의 앞부분과 겹칠 수 있다
    ck = await clocks(gid)
    seat = seat_clock(ck, current.seat_no)
    turn_start, start_remaining = ck["turn_started_at_ms"], seat["remaining_ms"]
    t_send_ms = await redis_ms()
    r = redis()
    try:
        recorded = [tuple(map(int, m.split("-"))) for m in await r.zrangebyscore("store:outages", turn_start, "+inf")]
    finally:
        await r.aclose()
    overlap = sum(max(0, min(e, t_send_ms) - max(s_, turn_start)) for s_, e in recorded)
    res.metrics["paused_sec"], res.metrics["exempt_overlap_ms"] = round(paused, 2), overlap
    # 면제량은 실제 정지에 붙어야 한다 — 하트비트 주기(200 ms) 단위 오차 + 명령 지연만 허용(독립 검토 #2 Q4: 예전에는 2~5 s 더 면제됐다)
    res.check(overlap <= paused * 1000 + 1_000, f"exempted {overlap} ms for a {paused:.1f} s stop")
    # 하한도 — 서버 기록끼리의 대조(clock_error_ms)는 장애 끝을 이르게 찍는 과소 면제를 못 잡는다(독립 검토 #3 중간).
    # paused 는 하네스가 pause/unpause 호출로 잰 외부 기준이다
    res.check(overlap >= paused * 1000 - 1_000, f"exempted only {overlap} ms for a {paused:.1f} s stop")
    await move_current(players, res, retry_busy_sec=5.0, strict=False)
    after = next(c["remaining_ms"] for c in players[0].turn["clocks"] if c["seat_no"] == current.seat_no)
    expected = start_remaining - (t_send_ms - turn_start - overlap) + 2000
    res.metrics["clock_error_ms"] = round(after - expected)
    res.check(abs(after - expected) <= 1500, f"outage not exempt: remaining {after} vs expected {expected:.0f}")
    return res


# ----- S6 SIGTERM 서버 유예 / SIGKILL 대조군 -----

SETTLE_MS = 10_000 + 2 * 5_000 + 1_000   # 워커 사망 판정 유예(하트비트 타임아웃 + 2 × socket_timeout + 스위퍼 주기)


async def new_outages(base: list[str]) -> list[tuple[int, int]]:
    r = redis()
    try:
        members = await r.zrangebyscore("store:outages", "-inf", "+inf")
    finally:
        await r.aclose()
    return [tuple(map(int, m.split("-"))) for m in members if m not in base]


async def outage_members() -> list[str]:
    r = redis()
    try:
        return await r.zrangebyscore("store:outages", "-inf", "+inf")
    finally:
        await r.aclose()


async def s6(pool: Pool, signal_kind: str = "term") -> Result:
    res = Result(f"s6_{signal_kind}")
    cs = await pool.any(2)
    gid = await friend_game(cs, "duel")
    before = await clocks(gid)
    base = await outage_members()
    current = cs[0].turn["current_seat_no"]
    seat_now = seat_clock(before, current)
    t1_ms = await redis_ms()
    r1 = seat_now["remaining_ms"] - (t1_ms - before["turn_started_at_ms"])   # 차례 좌석의 지금 게임 시계
    t = time.monotonic()
    if signal_kind == "term":
        await docker.action("server", "stop", t=30)
    else:
        await docker.action("server", "kill")
    codes = [await c.wait_closed(10) for c in cs]
    res.metrics["close_codes"] = codes
    if signal_kind == "term":
        res.check(all(code == 1012 for code in codes), f"close codes {codes}")
    else:
        await asyncio.sleep(12)                              # 전 워커 정지 — 접속 예산(30 s)을 가를 만큼 길게
    await docker.action("server", "start")
    await wait_server()
    res.metrics["downtime_sec"] = round(time.monotonic() - t, 2)

    if signal_kind == "term":
        await asyncio.sleep(max(0, 5 - (time.monotonic() - t)))
        mid = await clocks(gid)
        disc = seat_clock(mid, current)["disconnected_at_ms"]
        again = [await Client(c.user_id).open() for c in cs]
        pool.clients.extend(again)
        t_rc = await redis_ms()
        views = {}
        for c in again:
            views[c.user_id] = (await c.recv("game_state", timeout=8))["payload"]
        t2_ms = await redis_ms()
        after = await clocks(gid)
        for c in cs:
            spent = seat_clock(before, c.seat_no)["conn_remaining_ms"] - seat_clock(after, c.seat_no)["conn_remaining_ms"]
            res.metrics[f"seat{c.seat_no}_connection_spent_ms"] = spent
            res.check(spent <= 1000, f"seat {c.seat_no} lost {spent} ms of connection clock across a deploy")
        # 게임 시계는 끊긴 뒤 server_grace_game_ms(8 s)까지만 멈춘다 — 그 뒤는 흐른다(maze.md §8, 독립 검토 #2 Q8)
        r2 = next(x["remaining_ms"] for x in views[cs[0].user_id]["clocks"] if x["seat_no"] == current)
        frozen = min(8_000, t_rc - disc) if disc else 0
        expected = r1 - ((t2_ms - t1_ms) - frozen)
        res.metrics["game_clock_error_ms"] = round(r2 - expected)
        res.metrics["game_clock_frozen_ms"] = frozen
        res.check(abs(r2 - expected) <= 1500, f"game clock across deploy {r2} vs expected {expected:.0f}")
        logs = await docker.logs("server") + await docker.logs("proxy")   # 프록시 경유(M4-1) — 두 로그 모두
        res.check(not re.search(r"token=ey", logs), "raw token in server/proxy logs")
        res.metrics["raw_token_hits"] = len([1 for c in cs if token(c.user_id)[:20] in logs])
        return res

    # 서버 전체(워커 전부)가 함께 죽었다 — 전역 하트비트 공백 = 서비스 전체가 멈춘 시간이라 장애로 면제된다(§8).
    # 판별(독립 검토 #2 Q3): 스위퍼가 죽은 워커의 좌석을 끊김으로 처리한 뒤에(장애 끝 + 판정 유예) 재접속한다. 면제되면 소모량 ≈
    # 재접속 − 장애 끝, 면제가 없으면 정지 시간만큼 더 크다(접속 예산 30 s 안에서 둘을 가른다)
    for _ in range(40):
        fresh = await new_outages(base)
        if fresh:
            break
        await asyncio.sleep(0.5)
    res.check(len(fresh) == 1, f"whole-server stop outage records {fresh}")
    if not fresh:
        return res
    o_start, o_end = fresh[0]
    stopped_ms = int(res.metrics["downtime_sec"] * 1000)
    res.metrics["outage_ms"] = o_end - o_start
    res.check(o_end - o_start >= stopped_ms - 3_000, f"outage {o_end - o_start} ms shorter than the stop {stopped_ms} ms")
    wait_ms = o_end + SETTLE_MS + 2_000 - await redis_ms()
    await asyncio.sleep(max(0, wait_ms / 1000))
    mid = await clocks(gid)
    res.check(all(s["disconnected_at_ms"] is not None for s in mid["seats"]), "dead workers' seats were not dropped after the settle window")
    again = [await Client(c.user_id).open() for c in cs]
    pool.clients.extend(again)
    t_rc = await redis_ms()
    after = await clocks(gid)
    state = json.loads(await (rr := redis()).get(f"game:{gid}:state") or "null")
    await rr.aclose()
    reasons = [s["elimination_reason"] for s in (state or {}).get("seats", [])]
    res.metrics["reasons"] = reasons
    res.check(not any(reasons), f"whole-server stop penalized a seat: {reasons}")
    for c in cs:
        spent = seat_clock(before, c.seat_no)["conn_remaining_ms"] - seat_clock(after, c.seat_no)["conn_remaining_ms"]
        res.metrics[f"seat{c.seat_no}_connection_spent_ms"] = spent
        res.check(abs(spent - (t_rc - o_end)) <= 3_000,
                  f"seat {c.seat_no} spent {spent} ms, expected ≈ {t_rc - o_end} ms after recovery (outage exempt)")
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
    # 밀려난 연결의 끊김 확인은 정착 시간(3 s) 뒤 재시도 회차(1 s)에 돈다 — 그 뒤까지 본다(독립 검토 #2 Q3)
    noise = [m for m in await pa.drain(3.0 + 1.0 + 1.5) if m["type"] == "player_left"]
    raw = await clocks(gid)
    res.metrics["seat2"] = {k: seat_clock(raw, 2)[k] for k in ("owner", "disconnected_at_ms", "conn_remaining_ms")}
    res.metrics["conns"] = {"old": old.connected["payload"].get("worker"), "new": newer.worker,
                            "tries": len([c for c in pool.clients if c.user_id == pb.user_id])}
    res.check(not noise, "replacement announced as a disconnect")
    res.check(seat_clock(raw, 2)["disconnected_at_ms"] is None, "replacement charged the connection clock")
    return res


# ----- S9 연타 -----

async def s9(pool: Pool) -> Result:
    res = Result("s9_flood")
    (a, b), = await pool.on_workers([2])     # 같은 워커 — 그 워커의 수신 루프·버스를 연타가 막지 않는지(독립 검토 #2 Q9)
    cs = [a, b]
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


# ----- M4-1 프록시 경유 (P1~P4·오리진) — 클라이언트는 전부 Caddy 를 거친다 -----

REST_LIMIT = int(os.environ.get("HARNESS_REST_LIMIT", "1000"))
IP_LIMIT = int(os.environ.get("HARNESS_IP_LIMIT", "600"))


def fake_client_ip() -> str:
    """엣지가 붙일 클라이언트 주소 — 회차·시나리오마다 새 창이 되게 무작위(198.18.0.0/15, 벤치마크 대역)"""
    import random
    return f"198.{random.randint(18, 19)}.{random.randint(0, 255)}.{random.randint(1, 254)}"


async def edge(*args: str) -> dict:
    """edge 컨테이너에서 edge_probe.py — Caddy 가 신뢰하는 엣지로서 XFF 를 붙인다. 출력의 마지막 JSON 을 읽는다"""
    out = await docker.exec("edge", "python", "edge_probe.py", *args)
    found = re.findall(r"\{.*\}", out)
    if not found:
        raise RuntimeError(f"edge probe gave no JSON: {out[-300:]!r}")
    return json.loads(found[-1])


async def p1(pool: Pool) -> Result:
    """REST 리밋이 실제 클라이언트 IP 단위로 정확하다 — 엣지가 알려 준 IP 별 한 창, 위조 XFF 는 새 창을 못 연다"""
    res = Result("p1_rest_limit")
    a, b = fake_client_ip(), fake_client_ip()
    got = await edge("rest", a, str(REST_LIMIT + 1))
    res.metrics["via_edge"] = got
    res.check(got["sec"] < 50, f"edge probe took {got['sec']} s — longer than one window, inconclusive")
    res.check(got["ok"] == REST_LIMIT and got["limited"] == 1,
              f"client {a}: {got['ok']} allowed, {got['limited']} limited (limit {REST_LIMIT})")
    other = await edge("rest", b, "1")
    res.check(other["ok"] == 1, f"another client {b} was limited by {a}'s window")
    # 서버 직결, 요청마다 새 연결 — 두 워커에 나뉘어도 한 창(Redis 저장소). edge 는 서버가 믿지 않아 edge 주소 단위다
    direct = await edge("direct", str(REST_LIMIT + 1))
    res.metrics["direct_new_connections"] = direct
    res.check(direct["sec"] < 50, f"direct probe took {direct['sec']} s — longer than one window, inconclusive")
    res.check(len(direct["workers"]) >= 2, f"direct requests did not spread over workers: {direct['workers']}")
    res.check(direct["ok"] == REST_LIMIT and direct["limited"] == 1,
              f"direct: {direct['ok']} allowed, {direct['limited']} limited across workers (limit {REST_LIMIT})")
    # 하네스 클라이언트(신뢰 안 됨)가 위조 XFF 를 매번 바꿔 보낸다 — 자기 IP 한 창이라 한도 안에서 429 가 나와야 한다
    import httpx
    statuses = []
    async with httpx.AsyncClient(timeout=5) as client:
        for i in range(REST_LIMIT + 1):
            r = await client.get(f"{os.environ['SERVER_HTTP']}/", headers={"X-Forwarded-For": fake_client_ip()})
            statuses.append(r.status_code)
            if r.status_code == 429:
                break
    res.metrics["spoofed_until_429"] = len(statuses)
    res.check(429 in statuses, f"spoofed XFF opened a new window every time ({len(statuses)} requests, no 429)")
    return res


async def p2(pool: Pool) -> Result:
    """IP 접속 폭주 — 한 IP 의 한도 초과분은 토큰을 보기 전에 1013, 다른 IP·하네스 접속은 영향 없음"""
    res = Result("p2_ip_flood")
    flood, other = fake_client_ip(), fake_client_ip()
    got = await edge("ws", flood, str(IP_LIMIT + 5), "garbage")
    codes = got["codes"]
    res.metrics["flood"] = got["summary"]
    res.check(codes[:IP_LIMIT] == [4001] * IP_LIMIT, f"within the limit: {dict(got['summary'])}")
    res.check(codes[IP_LIMIT:] == [1013] * 5, f"over the limit: {codes[IP_LIMIT:]}")
    single = await edge("ws", other, "1", "garbage")
    res.check(single["codes"] == [4001], f"another IP {other} was cut: {single['codes']}")
    c = await Client(pool.free.pop()).open()                 # 하네스 자신(다른 IP) — 정상 접속
    pool.clients.append(c)
    res.check(c.connected is not None, "harness client could not connect")
    return res


async def p3(pool: Pool) -> Result:
    """프록시 재시작 — Caddy 가 소켓을 1001(going away)로 닫는다. 서버는 정상이었으므로 서버 유예가 아니다 — 재접속까지의
    공백은 일반 끊김으로 접속 시계에서 빠진다(1012 서버 유예와 구분)"""
    res = Result("p3_proxy_restart")
    cs = await pool.any(2)
    gid = await friend_game(cs, "duel")
    t0 = await redis_ms()
    await docker.action("proxy", "restart", t=10)
    codes = [await c.wait_closed(15) for c in cs]
    res.metrics["close_codes"] = codes
    res.check(all(code not in (1000, 1012) for code in codes), f"close codes {codes}")
    await wait_server()
    again = [await Client(c.user_id).open() for c in cs]
    pool.clients.extend(again)
    t1 = await redis_ms()
    raw = await clocks(gid)
    budget = int(os.environ.get("CONNECTION_BUDGET_MS", "30000"))
    spent = [budget - seat_clock(raw, s)["conn_remaining_ms"] for s in (1, 2)]
    res.metrics["gap_ms"], res.metrics["connection_spent_ms"] = t1 - t0, spent
    for s in spent:
        res.check(0 < s <= t1 - t0 + 1_000, f"connection clock spent {s} ms for a {t1 - t0} ms proxy restart")
    res.check(all(seat_clock(raw, s)["disconnected_at_ms"] is None for s in (1, 2)), "seat still disconnected")
    return res


async def p4(pool: Pool) -> Result:
    """로그 — 프록시·서버 로그 전체에 원문 토큰이 없다(Caddy 접속 로그 없음 + 서버 마스킹)"""
    res = Result("p4_logs")
    for service in ("proxy", "server"):
        logs = await docker.logs(service)
        hits = len(re.findall(r"token=ey", logs)) + len(re.findall(r"eyJhbGciOi", logs))
        res.metrics[f"{service}_raw_token_hits"] = hits
        res.check(hits == 0, f"raw token in {service} logs")
    return res


async def p_origin(pool: Pool) -> Result:
    """운영 설정(오리진 빈 목록) — 브라우저 오리진이 붙은 WS 는 토큰 전 403, Origin 없는 앱은 통과, CORS 헤더 없음"""
    import httpx
    from websockets.asyncio.client import connect as ws_connect
    from websockets.exceptions import InvalidStatus
    res = Result("p_origin")
    status = None
    try:
        sock = await ws_connect(f"{os.environ['SERVER_WS']}?token={token(pool.free[-1])}", origin="https://evil.example")
        await sock.close()
    except InvalidStatus as refused:
        status = refused.response.status_code
    res.metrics["ws_with_origin"] = status
    res.check(status == 403, f"WS with a browser origin got {status}")
    c = await Client(pool.free.pop()).open()
    pool.clients.append(c)
    res.check(c.connected is not None, "app (no Origin) could not connect")
    async with httpx.AsyncClient(timeout=5) as client:
        r = await client.options(f"{os.environ['SERVER_HTTP']}/health",
                                 headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "GET"})
    res.metrics["preflight"] = [r.status_code, r.headers.get("access-control-allow-origin")]
    res.check(r.headers.get("access-control-allow-origin") is None, "production allowed a browser origin")
    return res


SCENARIOS = {
    "s1": lambda p: s1(p, "duel"), "s1t": lambda p: s1(p, "trio"), "s2": s2, "s3": s3,
    "s4": lambda p: s4(p, "plain"), "s4c": lambda p: s4(p, "claim"), "s4k": lambda p: s4(p, "kill"),
    "s5": s5, "s6": lambda p: s6(p, "term"), "s6k": lambda p: s6(p, "kill"), "s7": s7, "s8": s8, "s9": s9,
    "p1": p1, "p2": p2, "p3": p3, "porigin": p_origin, "p4": p4,
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
            pool = Pool(await seed_users(200, f"r{run}{name}"))   # 분배가 치우쳐(E1) 양쪽을 채우려면 넉넉해야 한다
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
