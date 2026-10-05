"""
M3 7단계 B2 파일럿 — 반개방 끊김(ping 타임아웃)을 앱이 어떤 close code 로 보는가 (검토 L19)

판정 규칙(계획서 판단 5, 측정 전 고정): ping 타임아웃이 1011 이고 RST·정상 종료가 1011 이 아니면 "1011 이면 소급" 채택.
아니면 멈추고 질문한다.

    docker compose run --rm server-test python spikes/m3_stage7/l19_pilot.py

실제 uvicorn(서버 플래그는 prod 와 같은 websockets 구현) + ping 1 s / 1 s. 경우마다 3회.
"""

import asyncio
import base64
import os
import socket
import struct
import threading
import time

import uvicorn
from fastapi import FastAPI, WebSocket
from websockets.asyncio.client import connect

INTERVAL, TIMEOUT = 1.0, 1.0
SILENT_SEC = float(os.environ.get("SILENT_SEC", "4.5"))
seen: list[tuple[str, int, float]] = []
app = FastAPI()
_label = {"now": ""}


@app.websocket("/ws")
async def ws(websocket: WebSocket):
    await websocket.accept()
    opened = time.monotonic()
    while True:
        message = await websocket.receive()
        if message["type"] == "websocket.disconnect":
            seen.append((_label["now"], message.get("code"), time.monotonic() - opened))
            return


def raw_handshake(port: int) -> socket.socket:
    s = socket.create_connection(("127.0.0.1", port))
    key = base64.b64encode(os.urandom(16)).decode()
    s.sendall((f"GET /ws HTTP/1.1\r\nHost: x\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
               f"Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n").encode())
    buf = b""
    while b"\r\n\r\n" not in buf:
        buf += s.recv(4096)
    assert b" 101 " in buf.split(b"\r\n")[0], buf
    return s


async def case_silent(port):
    """핸드셰이크 뒤 아무것도 하지 않는다 — ping 에 pong 이 없다(TCP 는 열려 있다). 서버가 먼저 끊는지 본다"""
    s = raw_handshake(port)
    await asyncio.sleep(SILENT_SEC)
    s.close()


async def case_rst(port):
    s = raw_handshake(port)
    await asyncio.sleep(0.3)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, struct.pack("ii", 1, 0))
    s.close()  # RST


async def case_normal(port):
    async with connect(f"ws://127.0.0.1:{port}/ws") as c:
        await asyncio.sleep(0.3)
        await c.close(1000)


async def case_client_1011(port):
    async with connect(f"ws://127.0.0.1:{port}/ws") as c:
        await asyncio.sleep(0.3)
        await c.close(1011)


async def main():
    config = uvicorn.Config(app, host="127.0.0.1", port=0, log_level="warning", ws="websockets",
                            ws_ping_interval=INTERVAL, ws_ping_timeout=TIMEOUT)
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    while not server.started:
        await asyncio.sleep(0.02)
    port = server.servers[0].sockets[0].getsockname()[1]

    for name, case in [("silent", case_silent), ("rst", case_rst), ("normal", case_normal),
                       ("client_1011", case_client_1011)]:
        for i in range(3):
            _label["now"] = f"{name}#{i + 1}"
            await case(port)
            await asyncio.sleep(0.5)
    server.should_exit = True
    thread.join(5)
    for label, code, after in seen:
        print(f"{label:16s} code={code} after={after:.2f}s")


if __name__ == "__main__":
    asyncio.run(main())
