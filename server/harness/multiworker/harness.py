"""
하네스 공용 — Docker 엔진 제어, 유저 시드, WS 클라이언트, 워커 판별 (M3 7단계 C)

워커 판별: 서버가 WS_EXPOSE_WORKER=true 라 `connected.worker` 에 워커 id(`<pid>-<hex>`)가 온다(E1 의 pid 판별과 같은 방식).
"""

import asyncio
import base64
import json
import os
import socket
import time
from typing import Optional

import asyncpg
import httpx
from jose import jwt
from redis.asyncio import Redis
from websockets.asyncio.client import connect
from websockets.exceptions import ConnectionClosed

WS_URL = os.environ["SERVER_WS"]
HTTP_URL = os.environ["SERVER_HTTP"]
SECRET = os.environ["JWT_SECRET_KEY"]
PROJECT = os.environ["COMPOSE_PROJECT"]
RECV_SEC = 5.0


# ----- Docker 엔진 (소켓) -----

class Docker:
    def __init__(self):
        self.http = httpx.AsyncClient(transport=httpx.AsyncHTTPTransport(uds="/var/run/docker.sock"),
                                      base_url="http://docker", timeout=200)

    async def container(self, service: str) -> str:
        filters = json.dumps({"label": [f"com.docker.compose.project={PROJECT}",
                                        f"com.docker.compose.service={service}"]})
        r = await self.http.get("/containers/json", params={"all": "true", "filters": filters})
        r.raise_for_status()
        return r.json()[0]["Id"]

    async def exec(self, service: str, *cmd: str) -> str:
        cid = await self.container(service)
        r = await self.http.post(f"/containers/{cid}/exec",
                                 json={"Cmd": list(cmd), "AttachStdout": True, "AttachStderr": True})
        r.raise_for_status()
        out = await self.http.post(f"/exec/{r.json()['Id']}/start", json={"Detach": False})
        return out.text

    async def kill_pid(self, pid: int) -> None:
        await self.exec("server", "sh", "-c", 'kill -9 "$1"', "_", str(pid))

    async def action(self, service: str, verb: str, **params) -> None:
        cid = await self.container(service)
        r = await self.http.post(f"/containers/{cid}/{verb}", params=params)
        if r.status_code not in (204, 304):
            raise RuntimeError(f"{verb} {service}: {r.status_code} {r.text}")

    async def logs(self, service: str) -> str:
        cid = await self.container(service)
        r = await self.http.get(f"/containers/{cid}/logs", params={"stdout": "true", "stderr": "true"})
        return r.content.decode("utf-8", "replace")


# ----- 저장소 -----

def redis() -> Redis:
    return Redis.from_url(os.environ["REDIS_URL"], decode_responses=True)


async def seed_users(n: int, prefix: str) -> list[int]:
    """users 행 n개 — 서버의 신원 조회가 닉네임을 읽는다. 테이블은 서버 기동(create_all)이 만든다"""
    conn = await asyncpg.connect(os.environ["DATABASE_URL"])
    try:
        for _ in range(60):
            if await conn.fetchval("select to_regclass('public.users')"):
                break
            await asyncio.sleep(1)
        rows = []
        for i in range(n):
            rows.append(await conn.fetchval(
                """insert into users (nickname, password_hash, session_token, score, wins, losses,
                                      is_online, last_active_at, created_at)
                   values ($1, 'x', $2, 0, 0, 0, false, now(), now()) returning id""",
                f"{prefix[:9]}{os.urandom(4).hex()}{i}"[:20], os.urandom(16).hex()))
        return rows
    finally:
        await conn.close()


async def db_status(game_id: str) -> Optional[str]:
    conn = await asyncpg.connect(os.environ["DATABASE_URL"])
    try:
        return await conn.fetchval("select status from game_sessions where game_id = $1", game_id)
    finally:
        await conn.close()


def token(user_id: int) -> str:
    now = int(time.time())
    return jwt.encode({"sub": str(user_id), "typ": "access", "auth": "kakao", "iat": now, "exp": now + 3600},
                      SECRET, algorithm="HS256")


async def health() -> dict:
    async with httpx.AsyncClient(timeout=5) as client:
        return (await client.get(f"{HTTP_URL}/health")).json()


async def health_by_worker(tries: int = 60) -> dict[str, dict]:
    """/health 는 요청이 닿은 워커 하나의 값이다 — 두 워커가 다 보일 때까지 여러 번 묻는다"""
    seen: dict[str, dict] = {}
    for _ in range(tries):
        rt = (await health())["realtime"]
        seen[rt["worker_id"]] = rt
        if len(seen) >= 2:
            break
    return seen


async def wait_server(timeout: float = 60) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            if (await health())["realtime"]["started"]:
                return
        except Exception:
            pass
        await asyncio.sleep(0.5)
    raise RuntimeError("server did not come up")


# ----- WS 클라이언트 -----

class Client:
    def __init__(self, user_id: int):
        self.user_id = user_id
        self.ws = None
        self.received: list[dict] = []
        self._pending: list[dict] = []
        self._seq = 0
        self.worker: Optional[str] = None
        self.connected: Optional[dict] = None
        self.close_code: Optional[int] = None

    @property
    def pid(self) -> int:
        return int(self.worker.split("-")[0])

    async def open(self) -> "Client":
        self.ws = await connect(f"{WS_URL}?token={token(self.user_id)}", open_timeout=10)
        self.connected = await self.recv("connected")
        self.worker = self.connected["payload"].get("worker")
        return self

    async def send(self, type_: str, payload: Optional[dict] = None) -> int:
        self._seq += 1
        msg = {"type": type_, "seq": self._seq}
        if payload is not None:
            msg["payload"] = payload
        await self.ws.send(json.dumps(msg))
        return self._seq

    async def _next(self, timeout: float) -> dict:
        try:
            m = json.loads(await asyncio.wait_for(self.ws.recv(), timeout))
        except ConnectionClosed as exc:
            self.close_code = exc.rcvd.code if exc.rcvd is not None else 1006
            raise
        m["_t"] = time.monotonic()
        self.received.append(m)
        return m

    async def take(self, pred, timeout: float = RECV_SEC) -> dict:
        for i, m in enumerate(self._pending):
            if pred(m):
                return self._pending.pop(i)
        deadline = time.monotonic() + timeout
        while True:
            try:
                m = await self._next(max(0.01, deadline - time.monotonic()))
            except (asyncio.TimeoutError, TimeoutError):
                tail = [(x["type"], x.get("ack_seq"), x.get("payload", {}).get("error")) for x in self.received[-6:]]
                raise TimeoutError(f"user {self.user_id} worker {self.worker}: waited {timeout}s, last {tail}") from None
            if pred(m):
                return m
            self._pending.append(m)

    async def recv(self, type_: str, timeout: float = RECV_SEC, **match) -> dict:
        return await self.take(lambda m: m["type"] == type_ and all(
            m.get("payload", {}).get(k) == v for k, v in match.items()), timeout)

    async def reply(self, seq: int, timeout: float = RECV_SEC) -> dict:
        return await self.take(lambda m: m.get("ack_seq") == seq, timeout)

    async def drain(self, seconds: float) -> list[dict]:
        got, self._pending = self._pending, []
        deadline = time.monotonic() + seconds
        try:
            while True:
                got.append(await self._next(max(0.01, deadline - time.monotonic())))
        except (asyncio.TimeoutError, TimeoutError):
            return got
        except ConnectionClosed:
            return got

    async def wait_closed(self, timeout: float = RECV_SEC) -> int:
        try:
            deadline = time.monotonic() + timeout
            while True:
                await self._next(max(0.01, deadline - time.monotonic()))
        except ConnectionClosed:
            return self.close_code
        except (asyncio.TimeoutError, TimeoutError):
            return -1

    async def close(self) -> None:
        if self.ws is not None:
            try:
                await self.ws.close()
            except Exception:
                pass


class Pool:
    """시드된 유저 — 접속한 워커별로 나눠 둔다. 분배가 치우치므로(E1) 새 유저로 접속해 양쪽을 채운다"""

    def __init__(self, user_ids: list[int]):
        self.free = list(user_ids)
        self.clients: list[Client] = []

    async def on_workers(self, counts: list[int], max_tries: int = 80) -> list[list[Client]]:
        """counts[i] 명을 서로 다른 워커 i 에 — 워커 순서는 처음 본 순서"""
        workers: list[str] = []
        buckets: dict[str, list[Client]] = {}
        spare: list[Client] = []
        for _ in range(max_tries):
            if len(workers) == len(counts) and all(len(buckets[w]) >= n for w, n in zip(workers, counts)):
                break
            c = await Client(self.free.pop()).open()
            self.clients.append(c)
            if c.worker not in buckets:
                if len(workers) < len(counts):
                    workers.append(c.worker)
                    buckets[c.worker] = []
                else:
                    spare.append(c)
                    continue
            i = workers.index(c.worker)
            if len(buckets[c.worker]) < counts[i]:
                buckets[c.worker].append(c)
            else:
                spare.append(c)
        else:
            raise RuntimeError(f"could not spread clients over workers {counts}")
        for c in spare:
            await c.close()
        return [buckets[w][:n] for w, n in zip(workers, counts)]

    async def any(self, n: int) -> list[Client]:
        out = [await Client(self.free.pop()).open() for _ in range(n)]
        self.clients.extend(out)
        return out

    async def close_all(self) -> None:
        for c in self.clients:
            await c.close()
        self.clients.clear()


async def friend_game(players: list[Client], mode: str) -> str:
    """players[0] 이 방장 — 방 좌석 = 게임 좌석(호스트 1, 입장 순). game_id"""
    host = players[0]
    created = await host.reply(await host.send("create_room", {"mode": mode}))
    code = created["payload"]["room_code"]
    for p in players[1:]:
        await p.reply(await p.send("join_room", {"room_code": code}))
    for p in players:
        await p.send("ready")
    game_id = None
    for seat_no, p in enumerate(players, start=1):
        start = await p.recv("game_start", timeout=10)
        p.seat_no = start["payload"]["my_seat_no"]
        assert p.seat_no == seat_no, (p.seat_no, seat_no)
        p.view = (await p.recv("game_state"))["payload"]
        p.turn = (await p.recv("turn_change"))["payload"]
        game_id = start["payload"]["game_id"]
    return game_id


def legal_move(view: dict) -> tuple[int, int]:
    r, c = view["me"]["position"]["row"], view["me"]["position"]["col"]
    edges = {(e["row"], e["col"], e["orientation"]): e["wall"] for e in view["visible_edges"]}
    # 옆걸음부터 — 목표 쪽으로 곧장 가면 몇 수 만에 끝나 시나리오가 원하는 길이를 못 채운다
    options = [((r, c - 1), (r, c, "vertical")), ((r, c + 1), (r, c + 1, "vertical")),
               ((r - 1, c), (r, c, "horizontal")), ((r + 1, c), (r + 1, c, "horizontal"))]
    for (nr, nc), edge in options:
        if 0 <= nr <= 8 and 0 <= nc <= 8 and edges.get(edge) is False:
            return nr, nc
    raise RuntimeError("no open edge")


async def clocks(game_id: str) -> dict:
    client = redis()
    try:
        raw = await client.get(f"game:{game_id}:clocks")
        return json.loads(raw) if raw else {}
    finally:
        await client.aclose()


def seat_clock(raw: dict, seat_no: int) -> dict:
    return next(s for s in raw["seats"] if s["seat_no"] == seat_no)


def raw_ws_handshake(host: str, port: int, path: str) -> socket.socket:
    """ping 에 답하지 않는 원시 소켓 — 반개방 끊김(S7)"""
    s = socket.create_connection((host, port))
    key = base64.b64encode(os.urandom(16)).decode()
    s.sendall((f"GET {path} HTTP/1.1\r\nHost: {host}\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
               f"Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n").encode())
    buf = b""
    while b"\r\n\r\n" not in buf:
        buf += s.recv(4096)
    assert b" 101 " in buf.split(b"\r\n")[0], buf[:200]
    return s
