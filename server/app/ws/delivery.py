"""
이벤트 → 수신자별 메시지, 그리고 재동기화 (M3 4단계)

구독 버스(`bus.py`)가 수신자마다 부른다. 두 가지 일을 한다.

- `deliver(event, user_id)` — 이벤트 하나를 그 유저에게 보낼 메시지들로 바꾼다. 게임 이벤트는
  상태를 싣지 않으므로 Redis 에서 다시 읽어 **좌석별 화면**(`maze_view`, §6)을 붙인다
- `resync(user_id)` — 유저의 현재 활동(`user:{uid}:activity`)을 보고 지금 상태를 보낸다.
  Pub/Sub 재구독 직후(E5)와 7단계 재접속 직후에 쓴다

**와이어 형식은 잠정이다.** 메시지 `type` 은 이벤트 kind 를 그대로 쓰고, 좌석별 상태만
§12 의 `game_state` 로 보낸다. §12 타입·필드로의 대응은 7단계 핸들러를 쓸 때 확정한다.
"""

import logging
from typing import Optional

from app.db import redis_keys as keys
from app.db.redis_lock import require_redis
from app.services import activity, events
from app.services.events import Event
from app.services.matchmaking import Matchmaking, PendingMatch, matchmaking
from app.services.maze_game import MazeGameService, maze_games
from app.services.maze_view import game_view
from app.services.rooms import Rooms, rooms

logger = logging.getLogger(__name__)

GAME_STATE = "game_state"  # §12 — 좌석마다 내용이 다르다
QUEUE_STATUS = "queue_status"  # §12

_ID_FIELD = {"game": "game_id", "match": "match_id", "room": "code"}


def _message(type_: str, payload: dict) -> dict:
    return {"type": type_, "payload": payload}


def _my_seat(players: list[dict], user_id: int) -> Optional[int]:
    return next((p["seat_no"] for p in players if p.get("user_id") == user_id), None)


def _matched_payload(match: PendingMatch, user_id: int) -> dict:
    hint = events.matched(match).hint
    return {"match_id": match.match_id, **hint, "my_seat_no": _my_seat(hint["players"], user_id)}


class Delivery:
    """상태 없음 — 읽을 서비스만 주입받는다"""

    def __init__(
        self,
        games: MazeGameService = maze_games,
        room_service: Rooms = rooms,
        match_service: Matchmaking = matchmaking,
    ):
        self._games = games
        self._rooms = room_service
        self._matches = match_service

    async def deliver(self, event: Event, user_id: int) -> list[dict]:
        payload = {_ID_FIELD[event.scope]: event.scope_id, **event.hint}
        if "players" in event.hint:  # 좌석 목록이 있으면 받는 사람의 좌석을 알려 준다
            payload["my_seat_no"] = _my_seat(event.hint["players"], user_id)
        if event.scope == "game":
            payload["turn_count"] = event.seq

        out = [_message(event.kind, payload)]
        if event.kind in (events.GAME_STARTED, events.GAME_UPDATED):
            out += await self._game_state(event.scope_id, user_id)
        return out

    async def resync(self, user_id: int) -> list[dict]:
        current = await activity.current(require_redis(), user_id)
        if current is None:
            return []
        kind, rest = keys.parse_activity(current)

        if kind == "game":
            return await self._game_state(rest, user_id)
        if kind == "room":
            room = await self._rooms.get_room(rest)
            return [] if room is None else [
                _message(events.ROOM_UPDATED, {"code": room.code, **events.room_updated(room).hint})
            ]
        if kind == "match":
            match = await self._matches.get_match(rest)
            return [] if match is None else [
                _message(events.MATCHED, _matched_payload(match, user_id))
            ]
        if kind == "queue":
            game, _, mode = rest.partition(":")
            status = await self._matches.status(game, mode, user_id)
            return [_message(QUEUE_STATUS, {
                "game": status.game, "mode": status.mode,
                "position": status.position, "waiting_count": status.waiting_count,
            })]
        logger.warning("Unknown activity %r for user %s", current, user_id)
        return []

    async def _game_state(self, game_id: str, user_id: int) -> list[dict]:
        view = await game_view(game_id, user_id, games=self._games)
        return [] if view is None else [_message(GAME_STATE, view)]


delivery = Delivery()
