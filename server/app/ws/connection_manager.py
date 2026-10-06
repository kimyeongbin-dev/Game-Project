"""
WebSocket Connection Manager
WebSocket 연결 관리 — 이 워커 프로세스의 소켓만 안다

소켓 객체는 본래 프로세스 안에 있으므로 연결 맵(user_id → 소켓)만 여기 둔다.
누가 어느 게임·방에 속하는지는 Redis(`game:{id}:meta`·`room:{code}`)가 권위다.
게임·방 단위 전송은 이벤트 발행(`app/services/events.py`)과 구독 버스
(`app/ws/bus.py`)가 맡고, 버스는 수신자 목록과 `local_user_ids()` 의 교집합에만 보낸다.
"""

import asyncio
import logging
import secrets
from typing import Dict, Optional
from fastapi import WebSocket
from dataclasses import dataclass, field
from datetime import datetime
from app.core.config import settings
from app.core.time import utcnow

logger = logging.getLogger(__name__)


@dataclass
class PlayerConnection:
    """플레이어 연결 정보

    replaced: 같은 계정의 새 연결이 이 연결을 밀어냈다(4000). 핸들러는 이 연결의 끝을 **끊김으로 치지 않는다**.
    """
    websocket: WebSocket
    user_id: int
    nickname: str
    connected_at: datetime = field(default_factory=utcnow)
    conn_id: str = field(default_factory=lambda: secrets.token_hex(8))
    replaced: bool = False
    # 마지막으로 통지를 받은 활동 (scope, id) — 재구독 때 활동이 사라졌으면 그 끝을 알려 준다(검토 R6)
    last_activity: Optional[tuple[str, str]] = None


class ConnectionManager:
    """WebSocket 연결 관리자"""

    def __init__(self):
        # user_id -> PlayerConnection
        self._connections: Dict[int, PlayerConnection] = {}
        self._closing: set[asyncio.Task] = set()

    async def connect(self, websocket: WebSocket, user_id: int, nickname: str) -> PlayerConnection:
        """새 연결 등록"""
        await websocket.accept()

        # 기존 연결이 있으면 끊기 — 끊김으로 치지 않도록 먼저 표시한다
        if user_id in self._connections:
            old_conn = self._connections[user_id]
            old_conn.replaced = True
            try:
                await old_conn.websocket.close(code=4000, reason="다른 기기에서 연결됨")
            except Exception:
                pass

        connection = PlayerConnection(
            websocket=websocket,
            user_id=user_id,
            nickname=nickname
        )
        self._connections[user_id] = connection
        logger.info(f"WebSocket connected: {nickname} (user_id={user_id})")
        return connection

    async def disconnect(self, user_id: int, websocket: Optional[WebSocket] = None):
        """연결 해제

        websocket 을 넘기면 그 소켓이 지금 등록된 소켓일 때만 지운다. 4000 으로 교체된
        옛 연결의 핸들러가 끝나며 부르는 disconnect 가 새 연결을 지우지 않게 한다.
        """
        conn = self._connections.get(user_id)
        if conn is None:
            return
        if websocket is not None and conn.websocket is not websocket:
            return

        del self._connections[user_id]
        logger.info(f"WebSocket disconnected: {conn.nickname} (user_id={user_id})")

    async def replace_if_stale(self, user_id: int, current_conn_id: str) -> bool:
        """다른 워커에 같은 계정의 새 연결(current_conn_id)이 생겼다 — 이 워커의 옛 연결을 4000 으로 닫는다"""
        conn = self._connections.get(user_id)
        if conn is None or conn.conn_id == current_conn_id:
            return False
        conn.replaced = True
        del self._connections[user_id]
        try:
            await conn.websocket.close(code=4000, reason="다른 기기에서 연결됨")
        except Exception:
            pass
        return True

    def get_connection(self, user_id: int) -> Optional[PlayerConnection]:
        """연결 정보 조회"""
        return self._connections.get(user_id)

    def is_connected(self, user_id: int) -> bool:
        """연결 여부 확인"""
        return user_id in self._connections

    def local_user_ids(self) -> set[int]:
        """이 워커에 연결된 유저 — 버스가 수신자 목록과 교집합을 구한다"""
        return set(self._connections)

    async def send_personal(self, user_id: int, message: dict):
        """특정 유저에게 메시지 전송 — 시간 상한(ws_send_timeout_sec)을 넘기면 그 연결을 닫는다

        버스는 워커의 모든 이벤트를 한 루프에서 보낸다. 받지 않는 클라이언트 하나가 쓰기 버퍼를 막으면 같은 워커의 다른
        게임 통지가 함께 늦어지고 그 사이 시계는 흐른다(독립 검토 #1 R8). 늦은 소켓은 끊고, 재접속이 상태를 복원한다.
        """
        conn = self._connections.get(user_id)
        if conn:
            try:
                await asyncio.wait_for(conn.websocket.send_json(message), settings.ws_send_timeout_sec)
            except Exception as e:
                logger.warning("Failed to send message to %s: %s", user_id, type(e).__name__)
                await self.disconnect(user_id, conn.websocket)
                task = asyncio.create_task(_close_quietly(conn.websocket, 1013))
                self._closing.add(task)                 # 참조를 잡아 둔다 — 버려진 태스크는 GC 될 수 있다
                task.add_done_callback(self._closing.discard)

    async def broadcast(self, message: dict):
        """이 워커의 모든 연결에 메시지 전송"""
        for user_id in list(self._connections.keys()):
            await self.send_personal(user_id, message)

    # ===== 통계 =====

    def get_stats(self) -> dict:
        """연결 통계 (이 워커만)"""
        return {"total_connections": len(self._connections)}


async def _close_quietly(websocket: WebSocket, code: int) -> None:
    try:
        await asyncio.wait_for(websocket.close(code=code), settings.ws_send_timeout_sec)
    except Exception:
        pass


# 싱글톤 인스턴스
connection_manager = ConnectionManager()
