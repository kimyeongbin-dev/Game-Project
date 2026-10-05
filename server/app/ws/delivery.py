"""
내부 이벤트 → 수신자별 §12 메시지, 그리고 재동기화 (M3 4단계 자리 → 7단계 와이어 확정)

구독 버스(`bus.py`)가 수신자마다 부른다. 내부 이벤트 이름(`services/events.py`)은 서비스 어휘이고, 소켓으로 나가는
이름·모양은 **여기서만** 정한다(maze.md §12). 대응 표는 계획서 판단 1 / maze.md §12 "내부 이벤트 대응".

- 게임 이벤트에는 상태가 없다. Redis 에서 다시 읽은 **좌석별 스냅샷**(`maze_view.game_snapshot`)으로 만든다(§6)
- 게임 메시지 봉투에는 이벤트 번호 `version` 을 싣는다(검토 L23). 한 이벤트에서 나온 메시지는 같은 번호다
- 방 이벤트는 바꾼 사람(`change.actor_user_id`)에게 보내지 않는다 — 그 사람은 핸들러 응답(`ack_seq`)으로 받는다
- `user_id` 는 와이어에 싣지 않는다. 좌석은 `seat_no` 로만 가리킨다
- `resync(user_id)` 는 활동(`user:{uid}:activity`)에 맞는 현재 상태 — 재접속·재구독 직후. 끝난 게임이면 `game_end` 까지
"""

import logging
from typing import Optional

from app.core.time import Clock, redis_clock
from app.db import redis_keys as keys
from app.db.redis_lock import require_redis, store_errors
from app.schemas.ws_messages import WSMessageType as T
from app.services import activity, events
from app.services.events import Event
from app.services.matchmaking import Matchmaking, matchmaking
from app.services.maze_game import MazeGameService, maze_games
from app.services.maze_view import GameSnapshot, game_snapshot
from app.services.rooms import Rooms, rooms
from app.ws import wire
from app.ws.protocol import server_message

logger = logging.getLogger(__name__)


def _my_seat(players: list[dict], user_id: int) -> Optional[int]:
    return next((p["seat_no"] for p in players if p.get("user_id") == user_id), None)


class Delivery:
    """상태 없음 — 읽을 서비스만 주입받는다"""

    def __init__(
        self,
        games: MazeGameService = maze_games,
        room_service: Rooms = rooms,
        match_service: Matchmaking = matchmaking,
        clock: Clock = redis_clock,
    ):
        self._games = games
        self._rooms = room_service
        self._matches = match_service
        self._clock = clock

    # ----- 이벤트 -----

    async def deliver(self, event: Event, user_id: int) -> list[dict]:
        if event.scope == "game":
            return await self._game_event(event, user_id)
        if event.scope == "match":
            return await self._match_event(event, user_id)
        if event.scope == "room":
            return self._room_event(event, user_id)
        return []  # user 범위(session_replaced)는 버스가 직접 처리한다 — 메시지가 아니다

    async def _game_event(self, event: Event, user_id: int) -> list[dict]:
        game_id, hint, v = event.scope_id, event.hint, event.seq
        if await self._left(game_id, user_id):
            return []  # 탈락 후 구경을 그만두고 나갔다(§9) — 옛 게임 통지를 받지 않는다(검토 R5)

        if event.kind == events.GAME_VOIDED:
            return [await self._voided_end(game_id, user_id, v)]

        snap = await game_snapshot(game_id, user_id, games=self._games)
        if snap is None:
            return []
        view = snap.view

        if event.kind == events.GAME_STARTED:
            return [
                server_message(T.GAME_START, wire.game_start_payload(snap.meta, view["me"]["seat_no"]), version=v),
                server_message(T.GAME_STATE, wire.game_state_payload(view), version=v),
                server_message(T.TURN_CHANGE, wire.turn_change_payload(view, {}), version=v),
            ]
        if event.kind == events.SEAT_DISCONNECTED:
            return [server_message(T.PLAYER_LEFT, wire.player_left_reconnecting(
                hint["seat_no"], hint["grace_remaining_ms"], hint["survivors"]), version=v)]
        if event.kind == events.SEAT_RECONNECTED:
            return [server_message(T.PLAYER_JOINED, wire.player_reconnected(hint["seat_no"]), version=v)]
        if event.kind == events.GAME_UPDATED:
            out = []
            action = hint.get("last_action") or {}
            if action.get("kind") == events.ACTION_ELIMINATED:
                out.append(server_message(T.PLAYER_LEFT, wire.player_left_eliminated(
                    action["seat_no"], action.get("reason"), action["survivors"]), version=v))
            out.append(server_message(T.GAME_STATE, wire.game_state_payload(view), version=v))
            # 끝을 알리는 것은 끝낸 그 이벤트 하나다 — 늦게 전달된 이전 이벤트가 지금(종료) 상태를 다시 읽어도
            # game_end 를 또 보내지 않는다
            if hint.get("ended"):
                out.append(self._end(snap, v))
            else:
                out.append(server_message(T.TURN_CHANGE, wire.turn_change_payload(view, hint), version=v))
            return out
        logger.warning("Unknown game event %s", event.kind)
        return []


    async def claim_seat(self, game_id: str, user_id: int, owner: str) -> None:
        """이 연결이 그 좌석의 연결이다 — 게임 시작·재구독 때 버스가 부른다(검토 H4·R4). 크래시하면 스위퍼가 이 좌석을 찾는다"""
        try:
            await self._games.mark_connected(game_id, user_id, owner=owner)
        except Exception:  # 다음 재접속·행동이 다시 기록한다 — 전달을 막지 않는다
            logger.warning("Could not record seat owner for user %s in game %s", user_id, game_id)

    @staticmethod
    def _end(snap: GameSnapshot, v: int) -> dict:
        return server_message(
            T.GAME_END,
            wire.game_end_payload(snap.meta.game_id, snap.state, snap.meta, voided=snap.voided),
            version=v,
        )

    @staticmethod
    async def _left(game_id: str, user_id: int) -> bool:
        async with store_errors():
            return bool(await require_redis().sismember(keys.game_left(game_id), user_id))

    async def _voided_end(self, game_id: str, user_id: int, v: int) -> dict:
        """무효 — 장기 장애면 state 가 남아 full_board 를 채우고, 유실이면 남은 meta(없으면 빈 결과)로

        다시 읽은 state 가 진행 중이고 무효 표시도 없으면 전체 판을 만들지 않는다 — 함수 가드를 호출자가 우회하지
        않는다(검토 R12)
        """
        snap = await game_snapshot(game_id, user_id, games=self._games)
        if snap is not None:
            board_ok = snap.voided or snap.state.is_finished
            payload = wire.game_end_payload(game_id, snap.state if board_ok else None, snap.meta, voided=True)
        else:
            meta = await self._games.get_meta(game_id)
            payload = wire.game_end_payload(game_id, None, meta, voided=True)
        return server_message(T.GAME_END, payload, version=v)

    async def _match_event(self, event: Event, user_id: int) -> list[dict]:
        hint = event.hint
        if event.kind == events.MATCHED:
            now = await self._clock.now_ms()
            return [server_message(T.MATCHED, wire.matched_payload(
                event.scope_id, hint, _my_seat(hint["players"], user_id), now))]
        if event.kind == events.MATCH_READY:
            if _my_seat(hint["players"], user_id) == hint["seat_no"]:
                return []  # 준비한 사람은 핸들러 응답으로 받았다
            return [server_message(T.PLAYER_READY, {"seat_no": hint["seat_no"]})]
        if event.kind == events.MATCH_EXPIRED:
            if user_id in hint["requeued"]:
                status = await self._matches.status(hint["game"], hint["mode"], user_id)
                return [server_message(T.QUEUE_STATUS, wire.queue_payload(
                    status.mode, status.position, status.waiting_count, requeued=True))]
            return [server_message(T.QUEUE_STATUS, wire.queue_payload(hint["mode"], 0, 0, requeued=False))]
        logger.warning("Unknown match event %s", event.kind)
        return []

    @staticmethod
    def _room_event(event: Event, user_id: int) -> list[dict]:
        hint = event.hint
        if event.kind == events.ROOM_DISSOLVED:
            return [server_message(T.PLAYER_LEFT, {"seat_no": 1, "room_code": hint["code"], "room_closed": True})]
        if event.kind != events.ROOM_UPDATED:
            logger.warning("Unknown room event %s", event.kind)
            return []
        change = hint["change"]
        if change["actor_user_id"] == user_id:
            return []  # 바꾼 사람은 핸들러 응답으로 받았다
        room = wire.room_payload(hint["room"])
        seat_no = change["seat_no"]
        type_ = {
            events.ROOM_JOINED: T.PLAYER_JOINED,
            events.ROOM_READY: T.PLAYER_READY,
            events.ROOM_LEFT: T.PLAYER_LEFT,
        }.get(change["kind"])
        if type_ is None:  # created(받을 사람이 없다)·settings — 방 전체 스냅샷
            return [server_message(T.ROOM_JOINED, room)]
        return [server_message(type_, {"seat_no": seat_no, "room": room})]

    # ----- 재동기화 -----

    async def resync(self, user_id: int, last: Optional[tuple[str, str]] = None) -> list[dict]:
        """지금 활동의 상태. last: 이 연결이 마지막으로 통지를 받은 활동 — 활동이 그 사이 사라졌으면(끝남·해산·만료)
        그 끝을 알려 준다(검토 R6). 이벤트가 유실돼도 재구독으로 수렴한다"""
        current = await activity.current(require_redis(), user_id)
        if current is None:
            return await self._ended(user_id, last) if last is not None else []
        kind, rest = keys.parse_activity(current)

        if kind == "game":
            return await self.game_resync(rest, user_id)
        if kind == "room":
            room = await self._rooms.get_room(rest)
            return [] if room is None else [
                server_message(T.ROOM_JOINED, wire.room_payload(events.room_snapshot(room)))
            ]
        if kind == "match":
            match = await self._matches.get_match(rest)
            if match is None:
                return []
            hint = events.matched(match).hint
            now = await self._clock.now_ms()
            return [server_message(T.MATCHED, wire.matched_payload(
                match.match_id, hint, _my_seat(hint["players"], user_id), now))]
        if kind == "queue":
            game, _, mode = rest.partition(":")
            status = await self._matches.status(game, mode, user_id)
            return [server_message(T.QUEUE_STATUS, wire.queue_payload(
                status.mode, status.position, status.waiting_count))]
        logger.warning("Unknown activity %r for user %s", current, user_id)
        return []

    async def _ended(self, user_id: int, last: tuple[str, str]) -> list[dict]:
        scope, scope_id = last
        if scope == "game":
            if await self._left(scope_id, user_id):
                return []
            snap = await game_snapshot(scope_id, user_id, games=self._games)
            if snap is None or not (snap.state.is_finished or snap.voided):
                return []
            return [server_message(T.GAME_STATE, wire.game_state_payload(snap.view), version=snap.version),
                    self._end(snap, snap.version)]
        if scope == "room":
            return [server_message(T.PLAYER_LEFT, {"seat_no": None, "room_code": scope_id, "room_closed": True})]
        if scope == "match":
            return [server_message(T.QUEUE_STATUS, wire.queue_payload(None, 0, 0, requeued=False))]
        return []

    async def game_resync(self, game_id: str, user_id: int) -> list[dict]:
        """현재 화면 + 진행 중이면 turn_change, 끝났으면 game_end. 번호는 지금 값"""
        snap = await game_snapshot(game_id, user_id, games=self._games)
        if snap is None:
            return []
        v = snap.version
        last = (self._end(snap, v) if snap.state.is_finished or snap.voided
                else server_message(T.TURN_CHANGE, wire.turn_change_payload(snap.view, {}), version=v))
        return [server_message(T.GAME_STATE, wire.game_state_payload(snap.view), version=v), last]


delivery = Delivery()
