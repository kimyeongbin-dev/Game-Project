"""
좌석별 게임 화면 — 플레이어별 개별 전송의 필터 (maze.md §6, M3 4·5단계)

같은 게임이라도 좌석마다 다른 패킷을 만든다. 구독 버스(`app/ws/delivery.py`)가 이벤트를
받으면 수신자마다 이 함수로 Redis 의 현재 상태를 다시 읽어 만든다 — 이벤트에는 상태가 없다.
재접속·재구독 재동기화도 `game_view` 를 거치므로 저장된 발견 맵이 그대로 복원된다(§9).

- 시야는 `app/games/maze/core/vision.py` 가 계산한다. 누적 관측(발견 맵·마지막 목격)은
  `game:<id>:vision:<seat_no>` 에 있고, 플레이어 화면은 **자기 좌석 키만** 읽는다
- 탈락 좌석은 눈을 감는다 — 지금 보이는 것은 비고 발견 맵은 탈락 직전 그대로다
- 친구 방에서 관전을 허용했으면(meta.spectate_on_elimination) 탈락 좌석에게만 `spectator`
  (전체 판 + 생존자별 시야)를 붙인다. 다른 좌석의 관측을 읽는 경로는 이것 하나다
- 종료 후에도 안개는 유지된다. 전체 판 공개는 `game_end.full_board`(7단계) 몫이다
- 시계(M3 6단계): 좌석 전원의 게임 시계·접속 시계 잔량은 공개 정보다(§8). 조회 시각 기준 지연 정산 값이고
  탈락 좌석도 같은 값을 받는다. 위치·벽과 결합되는 값이 없다. 필드 이름은 잠정(§12 확정은 7단계)
"""

from typing import Optional

from app.games.maze import GameState
from app.games.maze.core.vision import SeatMemory, edges_payload, game_sight
from app.services.maze_game import GameMeta, MazeGameService, maze_games


def _player(seat_no: int, position) -> dict:
    return {"seat_no": seat_no, "position": position.to_dict()}


def vision_fields(state: GameState, seat_no: int, memory: SeatMemory) -> dict:
    """seat_no 가 지금 보는 것과 지금까지 본 것 (§6 상태 패킷의 시야 4필드)

    memory 는 저장된 누적 관측이다. 지금 시야를 한 번 더 더해(쓰지 않는다) 발견 ⊇ 지금 시야를 보장한다.
    visible_players 의 seat_no 집합이 others[].visible 을 정한다.
    """
    if state.seat(seat_no).is_eliminated:
        now_edges, now_players, seen = {}, (), memory
    else:
        now = game_sight(state, seat_no)
        now_edges, now_players = now.edges, now.players
        seen = memory.observe(now, state.turn_count)

    return {
        "discovered_edges": edges_payload(seen.edges),
        "visible_edges": edges_payload(now_edges),
        "visible_players": [_player(s, pos) for s, pos in now_players],
        "last_seen_players": [
            {**_player(s, pos), "seen_at_turn": turn}
            for s, (pos, turn) in sorted(seen.last_seen.items())
        ],
    }


def spectator_fields(state: GameState, survivors: dict[int, SeatMemory]) -> dict:
    """관전 패킷 — 전체 판과 생존자별 시야. 클라이언트가 '전체' / '한 명 따라가기' 를 고른다"""
    return {
        "walls": [w.to_dict() for w in state.wall_manager.walls],
        "positions": [_player(p.seat_no, p.position) for p in state.seats],
        "views": [
            {"seat_no": s, **vision_fields(state, s, memory)}
            for s, memory in sorted(survivors.items())
        ],
    }


def spectating(state: GameState, meta: GameMeta, seat_no: int) -> bool:
    """관전 패킷 대상인가 — 친구 방 설정이 켜져 있고 이 좌석이 탈락했다"""
    return meta.spectate_on_elimination and state.seat(seat_no).is_eliminated


def build_view(
    state: GameState,
    meta: GameMeta,
    seat_no: int,
    memory: SeatMemory,
    survivors: Optional[dict[int, SeatMemory]] = None,
    clocks: Optional[dict] = None,
) -> dict:
    """§6 상태 패킷. 내 정보 전체 + 시야 + 남의 공개 정보(닉네임·남은 벽·탈락·시계)만

    survivors 는 관전 대상일 때만 넘긴다(생존 좌석 → 누적 관측). clocks 는 공개 시계(§8).
    """
    me = state.seat(seat_no)
    vision = vision_fields(state, seat_no, memory)
    visible = {p["seat_no"] for p in vision["visible_players"]}
    nicknames = {p.seat_no: p.nickname for p in meta.players}

    view = {
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
        "clocks": clocks,
    }
    if survivors is not None and spectating(state, meta, seat_no):
        view["spectator"] = spectator_fields(state, survivors)
    return view


async def game_view(
    game_id: str, user_id: int, *, games: MazeGameService = maze_games
) -> Optional[dict]:
    """user_id 의 좌석에서 본 현재 화면. 게임이 없거나 좌석이 아니면 None

    좌석은 인증된 user_id 로만 정한다(meta.seat_of) — 클라이언트가 좌석을 고를 수 없다.
    락 없이 읽는 스냅샷이다. meta 는 불변이고 state·관측은 MGET 한 번이라 찢어진 읽기가 없다.
    """
    meta = await games.get_meta(game_id)
    if meta is None:
        return None
    seat_no = meta.seat_of(user_id)
    if seat_no is None:
        return None
    state, memories, clocks = await games.load_with_vision(game_id, [seat_no])
    if state is None:
        return None
    if not spectating(state, meta, seat_no):
        return build_view(state, meta, seat_no, memories[seat_no],
                          clocks=await games.public_clocks(state, clocks))

    # 관전: 생존자 관측까지 같은 스냅샷으로 다시 읽는다
    survivor_seats = [p.seat_no for p in state.survivors]
    state, memories, clocks = await games.load_with_vision(game_id, [seat_no, *survivor_seats])
    if state is None:
        return None
    return build_view(
        state, meta, seat_no, memories[seat_no],
        survivors={s: memories[s] for s in survivor_seats},
        clocks=await games.public_clocks(state, clocks),
    )
