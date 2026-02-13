"""
WebSocket Game Router
실시간 온라인 대전 WebSocket 엔드포인트
"""

import logging
import json
import asyncio
from typing import Optional
from dataclasses import dataclass
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query

from database import is_db_available
from database.config import get_session_factory
from database.memory_store import memory_store
from database.repository import UserRepository, RankingRepository
from services.quoridor_service import quoridor_service
from websocket import connection_manager, matchmaking_queue, room_manager
from websocket.matchmaking import MatchResult
from websocket.room_manager import RoomStatus
from schemas.ws_messages import WSMessageType

logger = logging.getLogger(__name__)

router = APIRouter(tags=["WebSocket"])


@dataclass
class SimpleUser:
    """WebSocket용 간단한 유저 객체"""
    id: int
    nickname: str
    score: float = 0.0


# ===== 유틸리티 함수 =====

async def get_user_by_token(token: str) -> Optional[SimpleUser]:
    """토큰으로 유저 조회 (DB/메모리 모드 지원)"""
    if not is_db_available():
        user = memory_store.get_by_token(token)
        if user:
            return SimpleUser(id=user.id, nickname=user.nickname, score=user.score)
        return None

    # DB 모드
    session_factory = get_session_factory()
    if session_factory is None:
        logger.error("Session factory is None even though DB is available")
        return None

    async with session_factory() as session:
        repo = UserRepository(session)
        user = await repo.get_by_token(token)
        if user:
            return SimpleUser(id=user.id, nickname=user.nickname, score=user.score)
        return None


async def send_error(websocket: WebSocket, code: str, message: str):
    """에러 메시지 전송"""
    await websocket.send_json({
        "type": "error",
        "code": code,
        "message": message
    })


# ===== 매칭 콜백 =====

async def on_match_found(match: MatchResult):
    """매칭 완료 시 콜백"""
    player1 = match.player1
    player2 = match.player2

    # 게임 생성
    game, _, _ = await quoridor_service.create_game(
        player1_name=player1.nickname,
        player2_name=player2.nickname,
        game_mode="ranked",
        is_ranked=True,
        player1_user_id=player1.user_id
    )

    game_id = game.game_id

    # 두 플레이어를 게임에 등록
    connection_manager.join_game(player1.user_id, game_id)
    connection_manager.join_game(player2.user_id, game_id)
    connection_manager.set_in_queue(player1.user_id, False)
    connection_manager.set_in_queue(player2.user_id, False)

    # 매칭 완료 알림
    await connection_manager.send_personal(player1.user_id, {
        "type": "match_found",
        "game_id": game_id,
        "opponent_nickname": player2.nickname,
        "opponent_score": player2.score,
        "you_are_player": 1,
        "message": "매칭 완료!"
    })

    await connection_manager.send_personal(player2.user_id, {
        "type": "match_found",
        "game_id": game_id,
        "opponent_nickname": player1.nickname,
        "opponent_score": player1.score,
        "you_are_player": 2,
        "message": "매칭 완료!"
    })

    # 게임 시작 알림
    game_state = game.to_dict()

    for user_id, player_num in [(player1.user_id, 1), (player2.user_id, 2)]:
        await connection_manager.send_personal(user_id, {
            "type": "game_start",
            "game_id": game_id,
            "game_mode": "ranked",
            "player1_nickname": player1.nickname,
            "player2_nickname": player2.nickname,
            "you_are_player": player_num,
            "turn_time_limit": 30,
            "game_state": game_state,
            "message": "게임이 시작되었습니다!"
        })

    logger.info(f"Ranked game started: {game_id} ({player1.nickname} vs {player2.nickname})")


# 매칭 콜백 설정
matchmaking_queue.set_match_callback(on_match_found)


# ===== WebSocket 엔드포인트 =====

@router.websocket("/ws/game")
async def websocket_game_endpoint(
    websocket: WebSocket,
    token: str = Query(..., description="세션 토큰")
):
    """
    게임 WebSocket 엔드포인트

    연결: ws://localhost:8000/ws/game?token=<session_token>

    메시지 타입:
    - join_queue: 랭킹전 매칭 큐 참가
    - leave_queue: 매칭 큐 나가기
    - create_room: 친구대전 방 생성
    - join_room: 친구대전 방 참가 (room_code 필요)
    - leave_room: 방 나가기
    - ready: 준비 완료
    - move: 폰 이동 (row, col)
    - wall: 벽 설치 (row, col, orientation)
    - surrender: 항복
    """
    # 토큰 인증
    user = await get_user_by_token(token)
    if not user:
        await websocket.close(code=4001, reason="Invalid token")
        return

    # 연결 등록
    conn = await connection_manager.connect(websocket, user.id, user.nickname)

    # 연결 성공 알림
    await websocket.send_json({
        "type": "connected",
        "user_id": user.id,
        "nickname": user.nickname,
        "message": "WebSocket 연결 성공"
    })

    try:
        while True:
            # 메시지 수신
            data = await websocket.receive_json()
            msg_type = data.get("type")

            if not msg_type:
                await send_error(websocket, "invalid_message", "type 필드가 필요합니다")
                continue

            # 메시지 처리
            try:
                await handle_message(websocket, user, data)
            except Exception as e:
                logger.error(f"Message handling error: {e}")
                await send_error(websocket, "internal_error", str(e))

    except WebSocketDisconnect:
        logger.info(f"WebSocket disconnected: {user.nickname}")
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
    finally:
        # 매칭 큐에서 제거
        matchmaking_queue.leave(user.id)

        # 방에서 나가기 처리
        room = room_manager.get_user_room(user.id)
        if room:
            await handle_leave_room(user)

        # 연결 해제
        await connection_manager.disconnect(user.id)


async def handle_message(websocket: WebSocket, user, data: dict):
    """메시지 처리"""
    msg_type = data.get("type")

    if msg_type == "join_queue":
        await handle_join_queue(websocket, user)

    elif msg_type == "leave_queue":
        await handle_leave_queue(websocket, user)

    elif msg_type == "create_room":
        turn_time_limit = data.get("turn_time_limit", 30)
        await handle_create_room(websocket, user, turn_time_limit)

    elif msg_type == "join_room":
        room_code = data.get("room_code")
        if not room_code:
            await send_error(websocket, "invalid_message", "room_code가 필요합니다")
            return
        await handle_join_room(websocket, user, room_code.upper())

    elif msg_type == "leave_room":
        await handle_leave_room(user)

    elif msg_type == "ready":
        await handle_ready(websocket, user)

    elif msg_type == "move":
        row = data.get("row")
        col = data.get("col")
        if row is None or col is None:
            await send_error(websocket, "invalid_message", "row와 col이 필요합니다")
            return
        await handle_move(websocket, user, row, col)

    elif msg_type == "wall":
        row = data.get("row")
        col = data.get("col")
        orientation = data.get("orientation")
        if row is None or col is None or not orientation:
            await send_error(websocket, "invalid_message", "row, col, orientation이 필요합니다")
            return
        await handle_wall(websocket, user, row, col, orientation)

    elif msg_type == "surrender":
        await handle_surrender(websocket, user)

    else:
        await send_error(websocket, "unknown_type", f"알 수 없는 메시지 타입: {msg_type}")


# ===== 메시지 핸들러 =====

async def handle_join_queue(websocket: WebSocket, user):
    """랭킹전 매칭 큐 참가"""
    if matchmaking_queue.is_in_queue(user.id):
        await send_error(websocket, "already_in_queue", "이미 매칭 큐에 있습니다")
        return

    if room_manager.get_user_room(user.id):
        await send_error(websocket, "in_room", "먼저 방에서 나가주세요")
        return

    position = matchmaking_queue.join(user.id, user.nickname, user.score)
    connection_manager.set_in_queue(user.id, True)
    logger.info(f"[대기열 참가] {user.nickname} (위치: {position})")

    await websocket.send_json({
        "type": "queue_joined",
        "position": position,
        "message": "매칭 큐에 참가했습니다"
    })

    # 큐 상태 전송
    status = matchmaking_queue.get_queue_status(user.id)
    await websocket.send_json({
        "type": "queue_status",
        **status
    })


async def handle_leave_queue(websocket: WebSocket, user):
    """매칭 큐 나가기"""
    if matchmaking_queue.leave(user.id):
        connection_manager.set_in_queue(user.id, False)
        logger.info(f"[대기열 나가기] {user.nickname}")
        await websocket.send_json({
            "type": "queue_left",
            "message": "매칭 큐에서 나왔습니다"
        })
    else:
        await send_error(websocket, "not_in_queue", "매칭 큐에 없습니다")


async def handle_create_room(websocket: WebSocket, user, turn_time_limit: Optional[int]):
    """친구대전 방 생성"""
    if matchmaking_queue.is_in_queue(user.id):
        await send_error(websocket, "in_queue", "먼저 매칭 큐에서 나가주세요")
        return

    try:
        room = room_manager.create_room(
            user_id=user.id,
            nickname=user.nickname,
            score=user.score,
            turn_time_limit=turn_time_limit
        )
        connection_manager.join_room(user.id, room.room_code)
        logger.info(f"[방 생성] {user.nickname} (코드: {room.room_code})")

        await websocket.send_json({
            "type": "room_created",
            "room_code": room.room_code,
            "turn_time_limit": room.turn_time_limit,
            "message": "방이 생성되었습니다. 친구에게 코드를 공유하세요."
        })
    except ValueError as e:
        await send_error(websocket, "room_error", str(e))


async def handle_join_room(websocket: WebSocket, user, room_code: str):
    """친구대전 방 참가"""
    if matchmaking_queue.is_in_queue(user.id):
        await send_error(websocket, "in_queue", "먼저 매칭 큐에서 나가주세요")
        return

    try:
        room = room_manager.join_room(
            room_code=room_code,
            user_id=user.id,
            nickname=user.nickname,
            score=user.score
        )
        connection_manager.join_room(user.id, room.room_code)
        logger.info(f"[방 참가] {user.nickname} -> {room.room_code} (호스트: {room.host.nickname})")

        # 참가자에게 알림
        await websocket.send_json({
            "type": "room_joined",
            "room_code": room.room_code,
            "host_nickname": room.host.nickname,
            "you_are_player": 2,
            "turn_time_limit": room.turn_time_limit,
            "message": f"{room.host.nickname}의 방에 참가했습니다"
        })

        # 호스트에게 알림
        await connection_manager.send_personal(room.host.user_id, {
            "type": "player_joined",
            "player_nickname": user.nickname,
            "message": f"{user.nickname}님이 입장했습니다"
        })

    except ValueError as e:
        await send_error(websocket, "room_error", str(e))


async def handle_leave_room(user):
    """방 나가기"""
    room = room_manager.get_user_room(user.id)
    if not room:
        return

    logger.info(f"[방 나가기] {user.nickname} <- {room.room_code}")
    room_code = room.room_code
    is_host = room.host.user_id == user.id
    other_player = room.guest if is_host else room.host

    room_manager.leave_room(user.id)
    await connection_manager.leave_room(user.id, room_code)

    # 본인에게 알림
    conn = connection_manager.get_connection(user.id)
    if conn:
        await connection_manager.send_personal(user.id, {
            "type": "room_left",
            "message": "방에서 나왔습니다"
        })

    # 상대방에게 알림
    if other_player:
        await connection_manager.send_personal(other_player.user_id, {
            "type": "player_left",
            "player_nickname": user.nickname,
            "room_closed": is_host,
            "message": f"{user.nickname}님이 나갔습니다" + (" (방이 닫혔습니다)" if is_host else "")
        })
        if is_host:
            await connection_manager.leave_room(other_player.user_id, room_code)


async def handle_ready(websocket: WebSocket, user):
    """준비 완료"""
    room = room_manager.get_user_room(user.id)
    if not room:
        await send_error(websocket, "not_in_room", "방에 참가하지 않았습니다")
        return

    if room.status != RoomStatus.READY:
        await send_error(websocket, "invalid_state", "아직 상대방이 없습니다")
        return

    room = room_manager.set_ready(user.id, True)
    logger.info(f"[준비 완료] {user.nickname} (방: {room.room_code})")

    # 상대방에게 알림
    other_player = room.guest if room.host.user_id == user.id else room.host
    await connection_manager.send_personal(other_player.user_id, {
        "type": "player_ready",
        "player_nickname": user.nickname,
        "message": f"{user.nickname}님이 준비 완료했습니다"
    })

    # 둘 다 준비되면 게임 시작
    if room.both_ready:
        await start_friend_game(room)


async def start_friend_game(room):
    """친구대전 게임 시작"""
    # 게임 생성
    game, _, _ = await quoridor_service.create_game(
        player1_name=room.host.nickname,
        player2_name=room.guest.nickname,
        game_mode="friend_match",
        is_ranked=False,
        player1_user_id=room.host.user_id
    )

    game_id = game.game_id
    room_manager.start_game(room.room_code, game_id)

    # 게임에 등록
    connection_manager.join_game(room.host.user_id, game_id)
    connection_manager.join_game(room.guest.user_id, game_id)

    game_state = game.to_dict()

    # 게임 시작 알림
    for player, player_num in [(room.host, 1), (room.guest, 2)]:
        await connection_manager.send_personal(player.user_id, {
            "type": "game_start",
            "game_id": game_id,
            "game_mode": "friend_match",
            "player1_nickname": room.host.nickname,
            "player2_nickname": room.guest.nickname,
            "you_are_player": player_num,
            "turn_time_limit": room.turn_time_limit,
            "game_state": game_state,
            "message": "게임이 시작되었습니다!"
        })

    logger.info(f"Friend game started: {game_id} ({room.host.nickname} vs {room.guest.nickname})")


async def handle_move(websocket: WebSocket, user, row: int, col: int):
    """폰 이동"""
    conn = connection_manager.get_connection(user.id)
    if not conn or not conn.current_game_id:
        await send_error(websocket, "not_in_game", "게임 중이 아닙니다")
        return

    game_id = conn.current_game_id
    game = await quoridor_service.get_game(game_id)

    if not game:
        await send_error(websocket, "game_not_found", "게임을 찾을 수 없습니다")
        return

    # 턴 체크 (플레이어 번호 확인)
    player_num = get_player_number(game_id, user.id)
    if game.current_turn != player_num:
        await send_error(websocket, "not_your_turn", "상대방 턴입니다")
        return

    # 이동 실행
    success, message, updated_game = await quoridor_service.move_pawn(game_id, row, col)

    if not success:
        await send_error(websocket, "invalid_move", message)
        return

    logger.info(f"[말 이동] {user.nickname} -> ({row}, {col}) (게임: {game_id[:8]})")

    # 게임 상태 전송
    await broadcast_game_state(game_id, updated_game, {
        "type": "move",
        "row": row,
        "col": col,
        "player": player_num
    })

    # 게임 종료 체크
    if updated_game.winner:
        await handle_game_end(game_id, updated_game)


async def handle_wall(websocket: WebSocket, user, row: int, col: int, orientation: str):
    """벽 설치"""
    conn = connection_manager.get_connection(user.id)
    if not conn or not conn.current_game_id:
        await send_error(websocket, "not_in_game", "게임 중이 아닙니다")
        return

    game_id = conn.current_game_id
    game = await quoridor_service.get_game(game_id)

    if not game:
        await send_error(websocket, "game_not_found", "게임을 찾을 수 없습니다")
        return

    # 턴 체크
    player_num = get_player_number(game_id, user.id)
    if game.current_turn != player_num:
        await send_error(websocket, "not_your_turn", "상대방 턴입니다")
        return

    # 벽 설치 실행
    success, message, updated_game = await quoridor_service.place_wall(game_id, row, col, orientation)

    if not success:
        await send_error(websocket, "invalid_wall", message)
        return

    logger.info(f"[벽 설치] {user.nickname} -> ({row}, {col}, {orientation}) (게임: {game_id[:8]})")

    # 게임 상태 전송
    await broadcast_game_state(game_id, updated_game, {
        "type": "wall",
        "row": row,
        "col": col,
        "orientation": orientation,
        "player": player_num
    })


async def handle_surrender(websocket: WebSocket, user):
    """항복"""
    conn = connection_manager.get_connection(user.id)
    if not conn or not conn.current_game_id:
        await send_error(websocket, "not_in_game", "게임 중이 아닙니다")
        return

    game_id = conn.current_game_id
    game = await quoridor_service.get_game(game_id)

    if not game:
        await send_error(websocket, "game_not_found", "게임을 찾을 수 없습니다")
        return

    player_num = get_player_number(game_id, user.id)
    winner = 2 if player_num == 1 else 1
    logger.info(f"[항복] {user.nickname} (게임: {game_id[:8]})")

    # 게임 종료 처리
    game.winner = winner
    game.status = game.status.__class__(f"player{winner}_win")

    await handle_game_end(game_id, game, reason="surrender", loser_id=user.id)


def get_player_number(game_id: str, user_id: int) -> int:
    """게임에서 유저의 플레이어 번호 조회"""
    players = connection_manager.get_game_players(game_id)
    player_list = sorted(players)  # 먼저 들어온 순서
    if user_id in player_list:
        return player_list.index(user_id) + 1
    return 0


async def broadcast_game_state(game_id: str, game, last_action: dict):
    """게임 상태 브로드캐스트"""
    game_state = game.to_dict()

    for user_id in connection_manager.get_game_players(game_id):
        player_num = get_player_number(game_id, user_id)
        your_turn = game.current_turn == player_num

        await connection_manager.send_personal(user_id, {
            "type": "game_state",
            "game_state": game_state,
            "last_action": last_action,
            "current_turn": game.current_turn,
            "your_turn": your_turn
        })


async def handle_game_end(game_id: str, game, reason: str = "goal_reached", loser_id: int = None):
    """게임 종료 처리"""
    winner = game.winner
    players = list(connection_manager.get_game_players(game_id))

    if len(players) < 2:
        return

    player1_id, player2_id = sorted(players)[:2]
    winner_id = player1_id if winner == 1 else player2_id
    loser_id = loser_id or (player2_id if winner == 1 else player1_id)

    winner_conn = connection_manager.get_connection(winner_id)
    loser_conn = connection_manager.get_connection(loser_id)

    winner_nickname = winner_conn.nickname if winner_conn else "Player"
    loser_nickname = loser_conn.nickname if loser_conn else "Player"

    # 랭킹전이면 점수 업데이트
    score_change = None
    winner_rank = None
    loser_rank = None
    is_ranked = game.game_mode.value == "ranked"

    if is_ranked:
        turn_bonus = 10 / max(1, game.turn_count)
        score_change = 3 + turn_bonus  # 승리 시

        if not is_db_available():
            # 메모리 모드에서 점수 업데이트
            memory_store.update_score(winner_id, score_change, True, game.turn_count)
            memory_store.update_score(loser_id, -1, False)
            winner_rank = memory_store.get_user_rank(winner_id)
            loser_rank = memory_store.get_user_rank(loser_id)
        else:
            # DB 모드에서 점수 업데이트
            session_factory = get_session_factory()
            if session_factory:
                async with session_factory() as session:
                    user_repo = UserRepository(session)
                    ranking_repo = RankingRepository(session)
                    await user_repo.update_score(winner_id, score_change, True, game.turn_count)
                    await user_repo.update_score(loser_id, -1, False)
                    await session.commit()
                    winner_rank = await ranking_repo.get_user_rank(winner_id)
                    loser_rank = await ranking_repo.get_user_rank(loser_id)

    final_state = game.to_dict()

    # 게임 종료 알림
    for user_id in players:
        is_winner = user_id == winner_id
        conn = connection_manager.get_connection(user_id)

        msg = {
            "type": "game_end",
            "winner": winner,
            "winner_nickname": winner_nickname,
            "reason": reason,
            "final_state": final_state,
            "you_win": is_winner,
            "message": "승리했습니다!" if is_winner else "패배했습니다."
        }

        if is_ranked and score_change:
            if is_winner:
                msg["score_change"] = score_change
                msg["new_rank"] = winner_rank
            else:
                msg["score_change"] = -1
                msg["new_rank"] = loser_rank

        await connection_manager.send_personal(user_id, msg)

    # 게임에서 플레이어 제거
    for user_id in players:
        await connection_manager.leave_game(user_id, game_id)

    # 방 정리 (친구대전인 경우)
    room = room_manager.get_room(game_id)
    if room:
        room_manager.end_game(room.room_code)

    logger.info(f"Game ended: {game_id} (winner: {winner_nickname}, reason: {reason})")
