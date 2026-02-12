"""
WebSocket Connection Manager
WebSocket 연결 관리
"""

import logging
import json
from typing import Dict, Optional, Set, Any
from fastapi import WebSocket
from dataclasses import dataclass, field
from datetime import datetime

logger = logging.getLogger(__name__)


@dataclass
class PlayerConnection:
    """플레이어 연결 정보"""
    websocket: WebSocket
    user_id: int
    nickname: str
    connected_at: datetime = field(default_factory=datetime.utcnow)
    current_game_id: Optional[str] = None
    current_room_code: Optional[str] = None
    is_in_queue: bool = False


class ConnectionManager:
    """WebSocket 연결 관리자"""

    def __init__(self):
        # user_id -> PlayerConnection
        self._connections: Dict[int, PlayerConnection] = {}
        # game_id -> set of user_ids
        self._game_players: Dict[str, Set[int]] = {}
        # room_code -> set of user_ids
        self._room_players: Dict[str, Set[int]] = {}

    async def connect(self, websocket: WebSocket, user_id: int, nickname: str) -> PlayerConnection:
        """새 연결 등록"""
        await websocket.accept()

        # 기존 연결이 있으면 끊기
        if user_id in self._connections:
            old_conn = self._connections[user_id]
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

    async def disconnect(self, user_id: int):
        """연결 해제"""
        if user_id not in self._connections:
            return

        conn = self._connections[user_id]

        # 게임에서 제거
        if conn.current_game_id:
            await self.leave_game(user_id, conn.current_game_id)

        # 방에서 제거
        if conn.current_room_code:
            await self.leave_room(user_id, conn.current_room_code)

        del self._connections[user_id]
        logger.info(f"WebSocket disconnected: {conn.nickname} (user_id={user_id})")

    def get_connection(self, user_id: int) -> Optional[PlayerConnection]:
        """연결 정보 조회"""
        return self._connections.get(user_id)

    def is_connected(self, user_id: int) -> bool:
        """연결 여부 확인"""
        return user_id in self._connections

    async def send_personal(self, user_id: int, message: dict):
        """특정 유저에게 메시지 전송"""
        conn = self._connections.get(user_id)
        if conn:
            try:
                await conn.websocket.send_json(message)
            except Exception as e:
                logger.warning(f"Failed to send message to {user_id}: {e}")
                await self.disconnect(user_id)

    async def send_to_game(self, game_id: str, message: dict, exclude_user: Optional[int] = None):
        """게임 참가자들에게 메시지 전송"""
        if game_id not in self._game_players:
            return

        for user_id in self._game_players[game_id]:
            if user_id != exclude_user:
                await self.send_personal(user_id, message)

    async def send_to_room(self, room_code: str, message: dict, exclude_user: Optional[int] = None):
        """방 참가자들에게 메시지 전송"""
        if room_code not in self._room_players:
            return

        for user_id in self._room_players[room_code]:
            if user_id != exclude_user:
                await self.send_personal(user_id, message)

    async def broadcast(self, message: dict):
        """모든 연결에 메시지 전송"""
        for user_id in list(self._connections.keys()):
            await self.send_personal(user_id, message)

    # ===== 게임 관리 =====

    def join_game(self, user_id: int, game_id: str):
        """게임 참가"""
        if game_id not in self._game_players:
            self._game_players[game_id] = set()
        self._game_players[game_id].add(user_id)

        conn = self._connections.get(user_id)
        if conn:
            conn.current_game_id = game_id

    async def leave_game(self, user_id: int, game_id: str):
        """게임 나가기"""
        if game_id in self._game_players:
            self._game_players[game_id].discard(user_id)
            if not self._game_players[game_id]:
                del self._game_players[game_id]

        conn = self._connections.get(user_id)
        if conn and conn.current_game_id == game_id:
            conn.current_game_id = None

    def get_game_players(self, game_id: str) -> Set[int]:
        """게임 참가자 목록"""
        return self._game_players.get(game_id, set())

    # ===== 방 관리 =====

    def join_room(self, user_id: int, room_code: str):
        """방 참가"""
        if room_code not in self._room_players:
            self._room_players[room_code] = set()
        self._room_players[room_code].add(user_id)

        conn = self._connections.get(user_id)
        if conn:
            conn.current_room_code = room_code

    async def leave_room(self, user_id: int, room_code: str):
        """방 나가기"""
        if room_code in self._room_players:
            self._room_players[room_code].discard(user_id)
            if not self._room_players[room_code]:
                del self._room_players[room_code]

        conn = self._connections.get(user_id)
        if conn and conn.current_room_code == room_code:
            conn.current_room_code = None

    def get_room_players(self, room_code: str) -> Set[int]:
        """방 참가자 목록"""
        return self._room_players.get(room_code, set())

    # ===== 매칭 큐 =====

    def set_in_queue(self, user_id: int, in_queue: bool):
        """매칭 큐 상태 설정"""
        conn = self._connections.get(user_id)
        if conn:
            conn.is_in_queue = in_queue

    def is_in_queue(self, user_id: int) -> bool:
        """매칭 큐 상태 확인"""
        conn = self._connections.get(user_id)
        return conn.is_in_queue if conn else False

    # ===== 통계 =====

    def get_stats(self) -> dict:
        """연결 통계"""
        return {
            "total_connections": len(self._connections),
            "active_games": len(self._game_players),
            "active_rooms": len(self._room_players),
            "players_in_games": sum(len(p) for p in self._game_players.values()),
            "players_in_rooms": sum(len(p) for p in self._room_players.values()),
        }


# 싱글톤 인스턴스
connection_manager = ConnectionManager()
