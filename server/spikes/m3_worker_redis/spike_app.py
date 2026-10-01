"""
M3 0단계 실측용 최소 앱 — 운영 코드가 아니다.

계획서: docs/plans/2026-10-01-M3-착수순서.md (0단계)
목적  : uvicorn 다중 워커에서 WS·lifespan·Pub/Sub·Redis 재시작이 실제로 어떻게
        동작하는지 측정한다. app/ 의 Redis 연결 계층(app.db.redis)을 그대로 써서
        운영과 같은 풀 설정(socket_timeout 등)으로 관측한다.

모든 이벤트를 JSON 한 줄로 stdout 에 남긴다 — `docker logs` 로 수집한다.
"""

import asyncio
import json
import os
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect

from app.db.redis import close_redis, get_redis, init_redis, is_redis_available

CHANNEL = "spike:bus"
_sockets: set[WebSocket] = set()


def log(event: str, **kw) -> None:
    print(json.dumps({"t": time.time(), "pid": os.getpid(), "event": event, **kw}), flush=True)


async def _subscriber() -> None:
    """워커마다 하나. 받은 메시지를 이 워커의 소켓 전부에 전달한다.

    재구독 루프는 일부러 단순하게 둔다 — redis-py 가 끊김을 어떻게 드러내는지
    (예외인가, 조용한 재연결인가)를 관측하는 것이 목적이다.
    """
    while True:
        r = get_redis()
        if r is None:
            log("sub_no_redis")
            await asyncio.sleep(1)
            continue
        try:
            ps = r.pubsub()
            await ps.subscribe(CHANNEL)
            log("sub_ready")
            async for msg in ps.listen():
                if msg["type"] != "message":
                    log("sub_meta", type=msg["type"])
                    continue
                for ws in list(_sockets):
                    try:
                        await ws.send_text(msg["data"])
                    except Exception:
                        _sockets.discard(ws)
            log("sub_listen_ended")
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log("sub_error", error=repr(exc))
            await asyncio.sleep(0.2)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    log("startup_begin")
    await init_redis()
    task = asyncio.create_task(_subscriber())
    log("startup_done", redis=is_redis_available())
    yield
    log("shutdown_begin", open_sockets=len(_sockets))
    task.cancel()
    await close_redis()
    log("shutdown_done")


app = FastAPI(lifespan=lifespan)


@app.get("/pid")
def pid() -> dict:
    return {"pid": os.getpid()}


async def _redis_op(op: str) -> dict:
    r = get_redis()
    t0 = time.perf_counter()
    try:
        if r is None:
            raise RuntimeError("get_redis() is None")
        if op == "redis_write":
            value = await r.incr("spike:counter")
        else:
            value = await r.get("spike:counter")
        return {"ok": True, "value": value, "ms": (time.perf_counter() - t0) * 1000}
    except Exception as exc:
        return {"ok": False, "err": repr(exc), "ms": (time.perf_counter() - t0) * 1000}


@app.websocket("/ws")
async def ws_endpoint(websocket: WebSocket) -> None:
    await websocket.accept()
    _sockets.add(websocket)
    log("ws_open", open_sockets=len(_sockets))
    await websocket.send_text(json.dumps({"kind": "hello", "pid": os.getpid()}))
    try:
        while True:
            msg = json.loads(await websocket.receive_text())
            op = msg.get("op")
            if op == "echo":
                await websocket.send_text(json.dumps({"kind": "echo", "pid": os.getpid(), "seq": msg.get("seq")}))
            elif op == "publish":
                r = get_redis()
                payload = json.dumps({"kind": "bus", "seq": msg["seq"], "sent": msg["sent"], "from_pid": os.getpid()})
                try:
                    await r.publish(CHANNEL, payload)
                except Exception as exc:
                    log("publish_error", error=repr(exc), seq=msg["seq"])
            elif op in ("redis_write", "redis_get"):
                res = await _redis_op(op)
                await websocket.send_text(json.dumps({
                    "kind": op, "seq": msg.get("seq"), "available": is_redis_available(), **res,
                }))
    except WebSocketDisconnect as exc:
        log("ws_close", code=exc.code)
    except Exception as exc:
        log("ws_error", error=repr(exc))
    finally:
        _sockets.discard(websocket)
