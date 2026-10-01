"""
좌석별 게임 화면 — 플레이어별 개별 전송의 필터 자리 (maze.md §6, M3 4단계)

같은 게임이라도 좌석마다 다른 패킷을 만든다. 구독 버스(`app/ws/delivery.py`)가 이벤트를
받으면 수신자마다 이 함수로 Redis 의 현재 상태를 다시 읽어 만든다 — 이벤트에는 상태가 없다.

**시야 계산은 5단계다.** 4단계의 `vision_fields` 는 아무것도 보여 주지 않는다. 화면이
불완전한 것은 감수하고, 남의 좌표·벽을 흘리지 않는 쪽을 기본값으로 둔다(§6 MUST NOT).
5단계는 `vision_fields` 만 바꾼다.
"""

from typing import Optional

from app.games.maze import GameState
from app.services.maze_game import GameMeta, MazeGameService, maze_games


def vision_fields(state: GameState, seat_no: int) -> dict:
    """seat_no 가 지금 보는 것과 지금까지 본 것 — 5단계에서 3×3 차폐 + 발견 맵으로 채운다

    반환 키: discovered_edges, visible_edges, visible_players, last_seen_players
    (§6 상태 패킷). visible_players 의 seat_no 집합이 others[].visible 을 정한다.
    """
    return {
        "discovered_edges": [],
        "visible_edges": [],
        "visible_players": [],
        "last_seen_players": [],
    }


def build_view(state: GameState, meta: GameMeta, seat_no: int) -> dict:
    """§6 상태 패킷. 내 정보 전체 + 남의 공개 정보(닉네임·남은 벽·탈락)만"""
    me = state.seat(seat_no)
    vision = vision_fields(state, seat_no)
    visible = {p["seat_no"] for p in vision["visible_players"]}
    nicknames = {p.seat_no: p.nickname for p in meta.players}

    return {
        "game_id": state.game_id,
        "turn_count": state.turn_count,
        "current_seat_no": state.current_seat_no,
        "finished": state.is_finished,
        "me": {
            "seat_no": me.seat_no,
            "position": me.position.to_dict(),
            "walls_remaining": me.walls_remaining,
            "goals": [g.to_dict() for g in me.goals],
            "eliminated": me.is_eliminated,
        },
        **vision,
        "others": [
            {
                "seat_no": p.seat_no,
                "nickname": nicknames.get(p.seat_no, ""),
                "walls_remaining": p.walls_remaining,
                "visible": p.seat_no in visible,
                "eliminated": p.is_eliminated,
            }
            for p in state.seats
            if p.seat_no != seat_no
        ],
    }


async def game_view(
    game_id: str, user_id: int, *, games: MazeGameService = maze_games
) -> Optional[dict]:
    """user_id 의 좌석에서 본 현재 화면. 게임이 없거나 좌석이 아니면 None

    락 없이 읽는 스냅샷이다. meta 는 불변이고 state 는 키 하나라 찢어진 읽기가 없다.
    """
    meta = await games.get_meta(game_id)
    if meta is None:
        return None
    seat_no = meta.seat_of(user_id)
    if seat_no is None:
        return None
    state = await games.load_game(game_id)
    if state is None:
        return None
    return build_view(state, meta, seat_no)
