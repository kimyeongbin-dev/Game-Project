"""
엣지 흉내 (M4-1) — `edge` 컨테이너 안에서 돈다. Caddy 가 이 컨테이너 주소만 신뢰하므로(CADDY_TRUSTED_PROXIES),
여기서 보내는 X-Forwarded-For 는 배포에서 엣지(Fly·ALB)가 붙이는 실제 클라이언트 주소와 같다. 클라이언트 IP 를
마음대로 정해 IP 별 리밋을 잴 수 있다. 하네스(client)가 Docker exec 로 부르고, 마지막 줄 JSON 을 읽는다.

    python edge_probe.py rest  <client_ip> <n> [hop]    프록시 경유 GET / n 회(동시 20) → 200·429 수. hop 이면 실제 엣지처럼
                                                         "<클라이언트가 보낸 위조 값>, <client_ip>" 로 덧붙인 형태
    python edge_probe.py direct <n>                      server:8000 에 직접(위조 XFF 를 매번 바꿔), 요청마다 새 연결 → 200 수
    python edge_probe.py ws    <client_ip> <n> <token>   프록시 경유 WS 접속 n 회 → close 코드 집계
"""

import asyncio
import json
import random
import sys
import time
from collections import Counter

import httpx
from websockets.asyncio.client import connect
from websockets.exceptions import ConnectionClosed

PROXY_HTTP = "http://proxy:8080"
PROXY_WS = "ws://proxy:8080/api/v1/ws/maze"
DIRECT_HTTP = "http://server:8000"


CONCURRENCY = 20   # 한 리밋 창(60 s) 안에 끝나게 — 순차로 새 연결 1000 개는 창을 넘겼다(파일럿)


def statuses_summary(statuses: list[int], started: float) -> dict:
    return {"ok": statuses.count(200), "limited": statuses.count(429), "n": len(statuses),
            "sec": round(time.monotonic() - started, 2)}


async def _many(n: int, one) -> list[int]:
    gate = asyncio.Semaphore(CONCURRENCY)

    async def run():
        async with gate:
            return await one()

    return list(await asyncio.gather(*(run() for _ in range(n))))


def spoofed() -> str:
    return f"203.0.113.{random.randint(1, 254)}"


async def rest(client_ip: str, n: int, hop: bool = False) -> dict:
    started = time.monotonic()
    async with httpx.AsyncClient(timeout=10) as client:
        async def one():
            # 엣지는 받은 XFF 뒤에 접속 주소를 덧붙인다 — 클라이언트가 왼쪽에 무엇을 넣든 키는 오른쪽의 실제 주소여야 한다
            xff = f"{spoofed()}, {client_ip}" if hop else client_ip
            return (await client.get(f"{PROXY_HTTP}/", headers={"X-Forwarded-For": xff})).status_code
        return statuses_summary(await _many(n, one), started)


async def direct(n: int) -> dict:
    """요청마다 새 TCP — uvicorn 마스터가 워커에 나눈다. 클라이언트는 하나(요청마다 만들면 SSL 컨텍스트 생성에 CPU 를 태워
    한 창 60 s 를 넘겼다 — 파일럿)"""
    started = time.monotonic()
    async with httpx.AsyncClient(timeout=10, limits=httpx.Limits(max_keepalive_connections=0)) as client:
        workers: Counter = Counter()

        async def one():
            # 서버는 프록시 주소만 믿는다 — edge 가 직결로 보낸 위조 XFF 는 무시되고 edge 주소 한 창이어야 한다
            r = await client.get(f"{DIRECT_HTTP}/health", headers={"Connection": "close", "X-Forwarded-For": spoofed()})
            if r.status_code == 200:   # 응답한 워커 — 두 워커에 나뉘었는지 본다(하네스는 WS_EXPOSE_WORKER=true)
                workers[r.json()["realtime"].get("worker_id")] += 1
            return r.status_code
        out = statuses_summary(await _many(n, one), started)
        out["workers"] = dict(workers)
        return out


async def ws(client_ip: str, n: int, token: str) -> dict:
    codes = []
    for _ in range(n):
        try:
            async with connect(f"{PROXY_WS}?token={token}", additional_headers={"X-Forwarded-For": client_ip},
                               open_timeout=5) as sock:
                try:
                    message = await asyncio.wait_for(sock.recv(), 5)
                    codes.append("message:" + json.loads(message).get("type", "?"))
                except ConnectionClosed as closed:
                    codes.append(closed.rcvd.code if closed.rcvd else "abnormal")
        except Exception as exc:
            codes.append(type(exc).__name__)
    return {"codes": [c for c in codes], "summary": dict(Counter(map(str, codes)))}


async def main(argv: list[str]) -> dict:
    kind = argv[0]
    if kind == "rest":
        return await rest(argv[1], int(argv[2]), hop=len(argv) > 3 and argv[3] == "hop")
    if kind == "direct":
        return await direct(int(argv[1]))
    if kind == "ws":
        return await ws(argv[1], int(argv[2]), argv[3])
    raise SystemExit(f"unknown probe {kind}")


if __name__ == "__main__":
    print(json.dumps(asyncio.run(main(sys.argv[1:]))), flush=True)
