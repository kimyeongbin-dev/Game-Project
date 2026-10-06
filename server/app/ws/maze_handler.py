"""
1인칭 미로 WebSocket 핸들러 — `/api/v1/ws/maze` (docs/api/games/maze.md §2·§3·§4·§5·§9·§12)

연결 하나의 수명을 맡는다. 상태는 갖지 않는다 — 큐·방·게임은 서비스(Redis 권위)에, 소켓은 연결 맵에 있다.

- **user_id 는 인증된 연결에서만.** 토큰 `sub` 로 정하고 페이로드의 좌석·유저·시각은 읽지 않는다(모델에 없다).
  좌석은 서비스가 `meta.seat_of(user_id)` 로 정한다. `eliminate(seat_no)` 같은 서버 행위는 여기 연결하지 않는다
- **소켓에는 §13 코드와 고정 문구만.** `ActionOutcome.state` 와 예외 문구는 보내지 않는다 — 예외는 서버 로그로만
- **수락된 행동에는 직접 응답이 없다.** 행위자도 수신자이므로 버스가 좌석별 화면을 보낸다(출처 하나). 거절만 `error`
- 인증 실패는 accept 후 즉시 close code(4001~4003) — ASGI 는 accept 전 close 를 HTTP 403 으로 바꿔 코드를 잃는다
- 재접속: 활동이 game 이면 `mark_connected(worker_id)` **후** 재동기화(접속 시계를 먼저 닫는다). 소켓이 끝나면 끊김을
  기록한다 — 단, 같은 계정의 새 연결로 밀려난(4000) 연결은 끊김으로 치지 않는다
"""

import logging
from dataclasses import dataclass, field
from typing import Awaitable, Callable, Optional

from fastapi import APIRouter, WebSocket
from starlette.websockets import WebSocketState

from app.core.config import settings
from app.core.origins import origin_allowed
from app.core.security import InvalidToken, verify_access_token
from app.core.worker import WORKER_ID
from app.db import redis_keys as keys
from app.db.redis import get_redis
from app.db.redis_lock import StoreUnavailable, store_errors
from app.games.maze import GameState
from app.schemas.ws_messages import WSMessageType as T
from app.services import activity, events
from app.services.activity import MultiplayerError
from app.services.events import Publisher, redis_publisher
from app.services.identity import Identity, IdentityDirectory, IdentityUnavailable, identity_directory
from app.services.matchmaking import Matchmaking, matchmaking
from app.services.maze_game import (
    GAME,
    GameBusy,
    GameNotFound,
    MazeGameService,
    StateVersionMismatch,
    maze_games,
)
from app.services.rooms import Rooms, rooms
from app.ws import wire
from app.ws.connection_manager import ConnectionManager, PlayerConnection, connection_manager
from app.ws.delivery import Delivery, delivery
from app.ws.rate_limit import ConnectLimiter, TokenBucket, connect_limiter, message_bucket
from app.ws.protocol import (
    CLOSE_INVALID_TOKEN,
    CLOSE_LOGIN_REQUIRED,
    CLOSE_NICKNAME_REQUIRED,
    CLOSE_POLICY_VIOLATION,
    CLOSE_TRY_AGAIN_LATER,
    ClientMessage,
    ProtocolError,
    error_message,
    parse_envelope,
    parse_payload,
    server_message,
)

logger = logging.getLogger(__name__)

PATH = "/api/v1/ws/maze"

# user:{uid}:conn 의 안전망 TTL — 정상 종료는 CAS 로 지우고, 크래시한 워커가 남긴 키만 이것으로 사라진다
USER_CONN_TTL_SEC = 86_400
_RELEASE_CONN_LUA = """
if redis.call('GET', KEYS[1]) == ARGV[1] then
    return redis.call('DEL', KEYS[1])
end
return 0
"""

# 서비스 예외 → §13 코드. 문구는 protocol.MESSAGES 에서만 나온다
_RETRYABLE = (GameBusy, StoreUnavailable)


@dataclass
class Session:
    """연결 하나 — 인증된 신원과 연결 맵 항목"""
    identity: Identity
    conn: PlayerConnection
    bucket: TokenBucket = field(default_factory=message_bucket)

    @property
    def user_id(self) -> int:
        return self.identity.user_id


DisconnectHook = Callable[[Session, Optional[int]], Awaitable[None]]


@dataclass
class MazeSocketHandler:
    manager: ConnectionManager = connection_manager
    games: MazeGameService = maze_games
    rooms: Rooms = rooms
    matches: Matchmaking = matchmaking
    delivery: Delivery = delivery
    identity: IdentityDirectory = identity_directory
    worker_id: str = WORKER_ID
    publisher: Publisher = redis_publisher
    limiter: ConnectLimiter = connect_limiter
    bucket_factory: Callable[[], TokenBucket] = message_bucket
    # 소켓이 끝났을 때 — 기본은 바로 끊김을 기록한다. 런타임(B1)이 추적·재시도하는 구현으로 바꾼다
    on_disconnect: Optional[DisconnectHook] = None
    _handlers: dict = field(init=False, repr=False)

    def __post_init__(self):
        self._handlers = {
            T.JOIN_QUEUE: self._join_queue,
            T.LEAVE_QUEUE: self._leave_queue,
            T.CREATE_ROOM: self._create_room,
            T.JOIN_ROOM: self._join_room,
            T.LEAVE_ROOM: self._leave_room,
            T.READY: self._ready,
            T.MOVE: self._move,
            T.WALL: self._wall,
            T.SURRENDER: self._surrender,
            T.CHAT: self._chat,
        }

    # ----- 수명 -----

    async def serve(self, websocket: WebSocket) -> None:
        session = await self._open(websocket)
        if session is None:
            return
        close_code: Optional[int] = None
        try:
            close_code = await self._loop(session)
        finally:
            await self.manager.disconnect(session.user_id, websocket)
            await self._closed(session, close_code)

    async def _open(self, websocket: WebSocket) -> Optional[Session]:
        # 브라우저 오리진 — 토큰을 보기 전에. accept 전 close 는 HTTP 403 이다(브라우저는 어차피 close 코드를 못 읽는다).
        # Starlette CORS 미들웨어는 WS 에 적용되지 않는다 (M4-1, app/core/origins.py)
        if not origin_allowed(websocket.headers.get("origin")):
            logger.info("WS rejected: origin not allowed")
            await websocket.close(code=CLOSE_POLICY_VIOLATION)
            return None
        try:
            claims = verify_access_token(websocket.query_params.get("token"))
        except InvalidToken as exc:
            logger.info("WS rejected: invalid token (%s)", exc)
            return await _reject(websocket, CLOSE_INVALID_TOKEN)
        if claims.is_anonymous:
            return await _reject(websocket, CLOSE_LOGIN_REQUIRED)
        # 접속 연타 — 재접속마다 신원 조회(DB)와 mark_connected(게임 락)가 돈다. 그 전에 끊는다(독립 검토 #1 R11)
        if not await self.limiter.allow(claims.user_id):
            return await _reject(websocket, CLOSE_TRY_AGAIN_LATER)
        try:
            identity = await self.identity.lookup(claims.user_id)
        except IdentityUnavailable as exc:
            logger.warning("WS rejected: identity store unavailable (%s)", exc)
            return await _reject(websocket, CLOSE_TRY_AGAIN_LATER)
        if identity is None:
            return await _reject(websocket, CLOSE_INVALID_TOKEN)   # 토큰은 맞지만 없는 계정
        if not identity.nickname:
            return await _reject(websocket, CLOSE_NICKNAME_REQUIRED)
        if get_redis() is None:  # 멀티플레이는 Redis 없이 성립하지 않는다
            return await _reject(websocket, CLOSE_TRY_AGAIN_LATER)

        conn = await self.manager.connect(websocket, identity.user_id, identity.nickname)
        conn.conn_id = f"{self.worker_id}:{conn.conn_id}"
        session = Session(identity, conn, self.bucket_factory())
        try:
            await self._claim_session(session)
            await self._welcome(session)
        except Exception as exc:
            # connected 를 못 보냈거나 좌석 소유를 못 가져갔다 — 반쯤 열린 연결로 두지 않는다(검토 R3·R7).
            # 닫고, 끊김 경로를 그대로 탄다(밀어낸 옛 연결의 좌석은 끊김으로 기록된다). 클라이언트는 재접속한다
            if isinstance(exc, _RETRYABLE + (StateVersionMismatch,)):
                logger.warning("WS open for %s failed: %s", identity.user_id, type(exc).__name__)
            else:
                logger.exception("WS open for %s failed", identity.user_id)
            await self.manager.disconnect(identity.user_id, websocket)
            try:
                await websocket.close(code=CLOSE_TRY_AGAIN_LATER)
            except Exception:
                pass
            await self._closed(session, CLOSE_TRY_AGAIN_LATER)
            return None
        return session

    async def _claim_session(self, session: Session) -> None:
        """같은 계정의 연결은 클러스터에 하나 — 이전 연결이 다른 워커에 있으면 그 워커가 4000 으로 닫는다(판단 4)

        같은 워커의 이전 연결은 connection_manager.connect 가 이미 닫았다. 이벤트는 이 워커에도 오지만 연결 id 가
        같으므로 아무 일도 없다.
        """
        # GET 뒤 SET — SET … GET 을 재시도하면 이전 값 대신 자기 값을 돌려받아 교체 통지를 잃는다(독립 검토 #2 Q5)
        async with store_errors():
            previous = await _redis().get(keys.user_conn(session.user_id))
            await _redis().set(keys.user_conn(session.user_id), session.conn.conn_id, ex=USER_CONN_TTL_SEC)
        if previous is not None and previous != session.conn.conn_id:
            await self.publisher.publish(events.session_replaced(session.user_id, session.conn.conn_id))

    async def _welcome(self, session: Session) -> None:
        """connected → (게임 중이면 재접속 처리) → 재동기화. 재접속은 재동기화보다 먼저다"""
        uid = session.user_id
        game_id = await self._current_game(uid)
        reconnect = None
        if game_id is not None:
            meta = await self.games.get_meta(game_id)
            seat_no = meta.seat_of(uid) if meta is not None else None
            if seat_no is not None:
                reconnect = {"game_id": game_id, "seat_no": seat_no}
                try:
                    await self.games.mark_connected(game_id, uid, owner=session.conn.conn_id)
                except GameNotFound:
                    reconnect = None

        payload = {"user_id": uid, "nickname": session.identity.nickname, "mmr": session.identity.mmr}
        if reconnect is not None:
            payload["reconnect"] = reconnect
        if settings.ws_expose_worker:
            payload["worker"] = self.worker_id
        await self._send(session, server_message(T.CONNECTED, payload))
        for message in await self.delivery.resync(uid):
            await self._send(session, message)

    async def _loop(self, session: Session) -> Optional[int]:
        """수신 루프. 끝난 이유의 close code 를 돌려준다(없으면 None)"""
        websocket = session.conn.websocket
        while True:
            message = await websocket.receive()
            if message["type"] == "websocket.disconnect":
                return message.get("code")
            text = message.get("text")
            if not session.bucket.allow():
                if session.bucket.exhausted:
                    await websocket.close(code=CLOSE_POLICY_VIOLATION)
                    return CLOSE_POLICY_VIOLATION
                await self._send(session, error_message("rate_limit_exceeded", _peek_seq(text)))
                continue
            if text is None:  # 바이너리 프레임
                await self._send(session, error_message("invalid_request"))
                continue
            await self._handle_text(session, text)

    async def _handle_text(self, session: Session, text: str) -> None:
        ack: Optional[int] = None
        try:
            request = parse_envelope(text)
            ack = request.seq
            reply = await self._handlers[request.type](session, request)
        except ProtocolError as exc:
            reply = error_message(exc.code, exc.ack_seq)
        except MultiplayerError as exc:
            reply = error_message(exc.code, ack)
        except GameNotFound:
            reply = error_message("not_in_game", ack)
        except _RETRYABLE:
            reply = error_message("server_busy", ack)
        except (StateVersionMismatch, ValueError) as exc:
            # 없는 모드 등 — 원인은 로그로만. 엔진 ValueError 문구에는 좌표가 있다
            logger.info("WS request from %s refused: %s", session.user_id, type(exc).__name__)
            reply = error_message("invalid_request", ack)
        except Exception:
            logger.exception("WS handler error for user %s", session.user_id)
            reply = error_message("internal_error", ack)
        if reply is not None:
            await self._send(session, reply)

    async def _closed(self, session: Session, close_code: Optional[int]) -> None:
        if self.on_disconnect is not None:   # 운영 경로 — 추적·재시도·정착 확인 (app/ws/runtime.py)
            await self.on_disconnect(session, close_code)
            return
        await self.release_session(session)
        if session.conn.replaced:
            return
        game_id = await self._current_game(session.user_id)
        if game_id is None:
            return
        try:
            await self.games.mark_disconnected(game_id, session.user_id, owner=session.conn.conn_id)
        except Exception:
            logger.warning("Could not record disconnect of %s in %s", session.user_id, game_id)

    async def release_session(self, session: Session) -> bool:
        """이 연결이 아직 그 유저의 연결이면 `user:{uid}:conn` 을 지운다(CAS) — 키가 있다 = 지금 어딘가 붙어 있다.
        실패하면 False — 런타임이 끊김 재시도와 함께 다시 지운다(독립 검토 #2 Q10)"""
        try:
            async with store_errors():
                await _redis().eval(_RELEASE_CONN_LUA, 1, keys.user_conn(session.user_id), session.conn.conn_id)
            return True
        except StoreUnavailable:
            return False

    # ----- 보조 -----

    async def _send(self, session: Session, message: dict) -> None:
        websocket = session.conn.websocket
        if websocket.client_state != WebSocketState.CONNECTED:
            return
        try:
            await websocket.send_json(message)
        except Exception:
            logger.debug("Send to %s failed (closing)", session.user_id)

    async def _activity(self, user_id: int) -> tuple[str, str]:
        current = await activity.current(_redis(), user_id)
        return keys.parse_activity(current) if current else ("", "")

    async def _current_game(self, user_id: int) -> Optional[str]:
        try:
            kind, rest = await self._activity(user_id)
        except StoreUnavailable:
            return None
        return rest if kind == "game" else None

    async def _game_of(self, session: Session) -> str:
        kind, rest = await self._activity(session.user_id)
        if kind != "game":
            raise MultiplayerError("not_in_game")
        return rest

    # ----- 큐 (§3) -----

    async def _join_queue(self, session: Session, request: ClientMessage) -> dict:
        body = parse_payload(request)
        result = await self.matches.join(GAME, body.mode, session.user_id,
                                         session.identity.nickname, session.identity.mmr)
        status = result.status
        if result.match is not None and session.user_id in {p.user_id for p in result.match.players}:
            # 이 입장으로 내 매치가 성사됐다 — matched 는 버스가 보낸다. 큐 응답은 자리 0
            return server_message(T.QUEUE_JOINED, wire.queue_payload(
                body.mode, 0, status.waiting_count, estimated_wait_sec=None), ack_seq=request.seq)
        return server_message(T.QUEUE_JOINED, wire.queue_payload(
            status.mode, status.position, status.waiting_count, estimated_wait_sec=None), ack_seq=request.seq)

    async def _leave_queue(self, session: Session, request: ClientMessage) -> dict:
        kind, rest = await self._activity(session.user_id)
        if kind != "queue":
            raise MultiplayerError("not_in_queue")
        game, _, mode = rest.partition(":")
        await self.matches.leave(game, mode, session.user_id)
        return server_message(T.QUEUE_STATUS, wire.queue_payload(mode, 0, 0, left=True), ack_seq=request.seq)

    # ----- 방 (§4) -----

    async def _create_room(self, session: Session, request: ClientMessage) -> dict:
        body = parse_payload(request)
        kind, _ = await self._activity(session.user_id)
        if kind == "room":  # 대기 중인 방장의 재전송 = 관전 설정 변경 (사용자 결정)
            room = await self.rooms.update_settings(session.user_id, body.mode, body.allow_spectate)
            return server_message(T.ROOM_JOINED, wire.room_payload(events.room_snapshot(room)), ack_seq=request.seq)
        room = await self.rooms.create_room(GAME, body.mode, session.user_id, session.identity.nickname,
                                            allow_spectate=body.allow_spectate)
        session.conn.last_activity = ("room", room.code)   # 방장은 자기 생성을 방송으로 받지 않는다 — 여기서 기억한다(R6)
        return server_message(T.ROOM_CREATED, wire.room_payload(events.room_snapshot(room)), ack_seq=request.seq)

    async def _join_room(self, session: Session, request: ClientMessage) -> dict:
        body = parse_payload(request)
        room = await self.rooms.join_room(body.room_code, session.user_id, session.identity.nickname)
        session.conn.last_activity = ("room", room.code)
        return server_message(T.ROOM_JOINED, wire.room_payload(events.room_snapshot(room)), ack_seq=request.seq)

    async def _leave_room(self, session: Session, request: ClientMessage) -> Optional[dict]:
        kind, rest = await self._activity(session.user_id)
        if kind == "game":
            # 시작 후 이탈 — 탈락한 좌석이면 구경을 그만두고 나가고(결과는 그대로), 생존 좌석이면 항복 (§9)
            seat_no = await self.games.leave_eliminated(rest, session.user_id)
            if seat_no is not None:
                session.conn.last_activity = None   # 스스로 나갔다 — 재구독 때 그 게임의 끝을 다시 알리지 않는다(Q7)
                return server_message(T.PLAYER_LEFT, {"seat_no": seat_no, "game_id": rest}, ack_seq=request.seq)
            return await self._surrender(session, request)
        if kind != "room":
            raise MultiplayerError("not_in_room")
        result = await self.rooms.leave_room(session.user_id)
        session.conn.last_activity = None       # 스스로 나갔다 — 남은 방을 "해산"으로 알리지 않는다(Q7)
        return server_message(T.PLAYER_LEFT, {"seat_no": result.seat_no, "room_code": result.room.code,
                                              "room_closed": result.dissolved}, ack_seq=request.seq)

    async def _ready(self, session: Session, request: ClientMessage) -> Optional[dict]:
        kind, rest = await self._activity(session.user_id)
        if kind == "match":
            outcome = await self.matches.mark_ready(rest, session.user_id)
        elif kind == "room":
            outcome = await self.rooms.set_ready(session.user_id)
        else:
            raise MultiplayerError("not_in_room" if kind != "queue" else "not_in_queue")
        if isinstance(outcome, GameState):
            return None  # 전원 준비 — game_start 는 버스가 보낸다
        seat_no = next(p.seat_no for p in outcome.players if p.user_id == session.user_id)
        return server_message(T.PLAYER_READY, {"seat_no": seat_no}, ack_seq=request.seq)

    # ----- 게임 (§5·§9) -----

    async def _move(self, session: Session, request: ClientMessage) -> Optional[dict]:
        body = parse_payload(request)
        outcome = await self.games.move(await self._game_of(session), session.user_id, body.row, body.col,
                                        owner=session.conn.conn_id)
        return _outcome_reply(outcome.rejection, request)

    async def _wall(self, session: Session, request: ClientMessage) -> Optional[dict]:
        body = parse_payload(request)
        outcome = await self.games.place_wall(await self._game_of(session), session.user_id,
                                              body.row, body.col, body.orientation, owner=session.conn.conn_id)
        return _outcome_reply(outcome.rejection, request)

    async def _surrender(self, session: Session, request: ClientMessage) -> Optional[dict]:
        outcome = await self.games.surrender(await self._game_of(session), session.user_id,
                                             owner=session.conn.conn_id)
        return _outcome_reply(outcome.rejection, request)

    async def _chat(self, session: Session, request: ClientMessage) -> dict:
        """유보(§12) — 탈락자는 발신 자체가 막혀 있다(§9). 나머지는 feature_disabled"""
        game_id = await self._current_game(session.user_id)
        if game_id is not None:
            meta, state = await self.games.get_meta(game_id), await self.games.load_game(game_id)
            seat_no = meta.seat_of(session.user_id) if meta is not None else None
            if state is not None and seat_no is not None and state.seat(seat_no).is_eliminated:
                return error_message("not_in_game", request.seq)
        return error_message("feature_disabled", request.seq)


def _peek_seq(text: Optional[str]) -> Optional[int]:
    """리밋에 걸린 요청의 ack_seq — 봉투만 본다(처리하지 않는다)"""
    if text is None:
        return None
    try:
        return parse_envelope(text).seq
    except ProtocolError as exc:
        return exc.ack_seq


def _outcome_reply(rejection: Optional[str], request: ClientMessage) -> Optional[dict]:
    """거절이면 코드만 — ActionOutcome.state 는 전체 상태라 보내지 않는다. 수락이면 버스가 화면을 보낸다"""
    return None if rejection is None else error_message(rejection, request.seq)


def _redis():
    client = get_redis()
    if client is None:
        raise StoreUnavailable("redis unavailable")
    return client


async def _reject(websocket: WebSocket, code: int) -> None:
    await websocket.accept()
    await websocket.close(code=code)
    return None


maze_handler = MazeSocketHandler()


def build_router(handler: MazeSocketHandler) -> APIRouter:
    router = APIRouter()

    @router.websocket(PATH)
    async def maze_socket(websocket: WebSocket):
        await handler.serve(websocket)

    return router


router = build_router(maze_handler)
