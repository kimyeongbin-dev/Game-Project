"""
Room Manager
친구대전 방 관리 시스템
"""

import logging
import random
import string
from typing import Optional, Dict
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

logger = logging.getLogger(__name__)


class RoomStatus(str, Enum):
    """방 상태"""
    WAITING = "waiting"     # 호스트만 있음
    READY = "ready"         # 게스트 입장, 준비 대기
    PLAYING = "playing"     # 게임 진행 중
    FINISHED = "finished"   # 게임 종료


@dataclass
class RoomPlayer:
    """방 참가자 정보"""
    user_id: int
    nickname: str
    is_host: bool
    is_ready: bool = False
    score: float = 0.0


@dataclass
class GameRoom:
    """게임 방"""
    room_code: str
    host: RoomPlayer
    guest: Optional[RoomPlayer] = None
    status: RoomStatus = RoomStatus.WAITING
    game_id: Optional[str] = None
    turn_time_limit: Optional[int] = 30  # 턴 제한 시간 (초)
    created_at: datetime = field(default_factory=datetime.utcnow)

    @property
    def is_full(self) -> bool:
        return self.guest is not None

    @property
    def both_ready(self) -> bool:
        if not self.guest:
            return False
        return self.host.is_ready and self.guest.is_ready

    def get_player(self, user_id: int) -> Optional[RoomPlayer]:
        if self.host.user_id == user_id:
            return self.host
        if self.guest and self.guest.user_id == user_id:
            return self.guest
        return None

    def get_player_number(self, user_id: int) -> int:
        """플레이어 번호 (1: 호스트, 2: 게스트)"""
        if self.host.user_id == user_id:
            return 1
        if self.guest and self.guest.user_id == user_id:
            return 2
        return 0


class RoomManager:
    """방 관리자"""

    ROOM_CODE_LENGTH = 6
    MAX_ROOMS = 1000  # 최대 방 개수

    def __init__(self):
        self._rooms: Dict[str, GameRoom] = {}
        self._user_rooms: Dict[int, str] = {}  # user_id -> room_code

    def _generate_room_code(self) -> str:
        """고유한 방 코드 생성"""
        chars = string.ascii_uppercase + string.digits
        for _ in range(100):  # 최대 100번 시도
            code = ''.join(random.choices(chars, k=self.ROOM_CODE_LENGTH))
            if code not in self._rooms:
                return code
        raise RuntimeError("Failed to generate unique room code")

    def create_room(
        self,
        user_id: int,
        nickname: str,
        score: float = 0.0,
        turn_time_limit: Optional[int] = 30
    ) -> GameRoom:
        """방 생성"""
        # 이미 방에 있으면 에러
        if user_id in self._user_rooms:
            raise ValueError("이미 다른 방에 참가 중입니다")

        # 최대 방 개수 체크
        if len(self._rooms) >= self.MAX_ROOMS:
            raise RuntimeError("서버에 방이 너무 많습니다. 잠시 후 다시 시도해주세요.")

        room_code = self._generate_room_code()
        host = RoomPlayer(
            user_id=user_id,
            nickname=nickname,
            is_host=True,
            score=score
        )
        room = GameRoom(
            room_code=room_code,
            host=host,
            turn_time_limit=turn_time_limit
        )

        self._rooms[room_code] = room
        self._user_rooms[user_id] = room_code
        logger.info(f"Room created: {room_code} by {nickname}")
        return room

    def join_room(
        self,
        room_code: str,
        user_id: int,
        nickname: str,
        score: float = 0.0
    ) -> GameRoom:
        """방 참가"""
        # 이미 방에 있으면 에러
        if user_id in self._user_rooms:
            existing_code = self._user_rooms[user_id]
            if existing_code == room_code:
                return self._rooms[room_code]
            raise ValueError("이미 다른 방에 참가 중입니다")

        # 방 찾기
        room = self._rooms.get(room_code)
        if not room:
            raise ValueError("존재하지 않는 방입니다")

        # 방 상태 체크
        if room.status != RoomStatus.WAITING:
            raise ValueError("이미 게임이 시작된 방입니다")

        if room.is_full:
            raise ValueError("방이 가득 찼습니다")

        # 게스트로 참가
        room.guest = RoomPlayer(
            user_id=user_id,
            nickname=nickname,
            is_host=False,
            score=score
        )
        room.status = RoomStatus.READY
        self._user_rooms[user_id] = room_code
        logger.info(f"Player joined room: {nickname} -> {room_code}")
        return room

    def leave_room(self, user_id: int) -> Optional[GameRoom]:
        """방 나가기"""
        if user_id not in self._user_rooms:
            return None

        room_code = self._user_rooms.pop(user_id)
        room = self._rooms.get(room_code)
        if not room:
            return None

        # 호스트가 나가면 방 삭제
        if room.host.user_id == user_id:
            # 게스트도 방에서 제거
            if room.guest:
                self._user_rooms.pop(room.guest.user_id, None)
            del self._rooms[room_code]
            logger.info(f"Room deleted: {room_code} (host left)")
            return room

        # 게스트가 나가면 게스트만 제거
        if room.guest and room.guest.user_id == user_id:
            room.guest = None
            room.status = RoomStatus.WAITING
            logger.info(f"Guest left room: {room_code}")
            return room

        return room

    def set_ready(self, user_id: int, is_ready: bool) -> Optional[GameRoom]:
        """준비 상태 설정"""
        room = self.get_user_room(user_id)
        if not room:
            return None

        player = room.get_player(user_id)
        if player:
            player.is_ready = is_ready
        return room

    def start_game(self, room_code: str, game_id: str) -> Optional[GameRoom]:
        """게임 시작"""
        room = self._rooms.get(room_code)
        if not room:
            return None

        room.status = RoomStatus.PLAYING
        room.game_id = game_id
        return room

    def end_game(self, room_code: str) -> Optional[GameRoom]:
        """게임 종료"""
        room = self._rooms.get(room_code)
        if not room:
            return None

        room.status = RoomStatus.FINISHED
        return room

    def get_room(self, room_code: str) -> Optional[GameRoom]:
        """방 조회"""
        return self._rooms.get(room_code)

    def get_user_room(self, user_id: int) -> Optional[GameRoom]:
        """유저가 속한 방 조회"""
        room_code = self._user_rooms.get(user_id)
        if room_code:
            return self._rooms.get(room_code)
        return None

    def delete_room(self, room_code: str):
        """방 삭제"""
        room = self._rooms.get(room_code)
        if room:
            self._user_rooms.pop(room.host.user_id, None)
            if room.guest:
                self._user_rooms.pop(room.guest.user_id, None)
            del self._rooms[room_code]
            logger.info(f"Room deleted: {room_code}")

    def get_stats(self) -> dict:
        """방 통계"""
        waiting = sum(1 for r in self._rooms.values() if r.status == RoomStatus.WAITING)
        ready = sum(1 for r in self._rooms.values() if r.status == RoomStatus.READY)
        playing = sum(1 for r in self._rooms.values() if r.status == RoomStatus.PLAYING)

        return {
            "total_rooms": len(self._rooms),
            "waiting_rooms": waiting,
            "ready_rooms": ready,
            "playing_rooms": playing,
        }


# 싱글톤 인스턴스
room_manager = RoomManager()
