"""
§12 페이로드 빌더 — 순수 함수 (maze.md §5·§8·§9·§10)

`delivery` 가 Redis 에서 다시 읽은 스냅샷으로 수신자별 메시지를 만들 때 쓴다. 상태 객체를 그대로 직렬화하는 함수는
없다 — 여기 있는 함수만 소켓으로 나가는 모양을 정한다.

- 시계: 좌석별 게임 시계·접속 시계 잔량과 연결 여부는 공개 정보다(§8). 소진 예정 시각은 ISO 8601 UTC(`Z`)
- `last_action` 은 행위자와 종류만 — 좌표는 없다(§6). 행동이 아닌 차례 이동(시작·탈락)이면 `null`
- **`full_board` 는 끝난 게임에서만 만들 수 있다.** 진행 중 상태로 부르면 ValueError — 경기 중 전체 맵이 나갈 경로를
  함수 수준에서 막는다(§10)
- MMR 필드는 지금 언제나 `null` — 산정은 인증·MMR 작업 몫이다(임시)
"""

from datetime import datetime, timezone
from typing import Optional

from app.games.maze import GameState
from app.services.maze_game import GameMeta, seat_results

ACTION_KINDS = frozenset({"move", "wall"})   # §5 last_action.kind
RESULT_VOID = "void"
END_SERVER_FAULT = "server_fault"


def iso_utc(epoch_ms: Optional[int]) -> Optional[str]:
    """epoch ms → `2026-10-01T09:34:28.123Z` (platform.md §0 시간 형식, ms 정밀도)"""
    if epoch_ms is None:
        return None
    stamp = datetime.fromtimestamp(epoch_ms / 1000, tz=timezone.utc)
    return stamp.strftime("%Y-%m-%dT%H:%M:%S.") + f"{stamp.microsecond // 1000:03d}Z"


def clocks_wire(public: Optional[dict], *, finished: bool) -> tuple[Optional[list], Optional[str]]:
    """`maze_clock.public_view` → (`clocks`, `clock_expires_at`). 끝난 게임은 소진 예정이 없다"""
    if public is None:
        return None, None
    seats = [
        {
            "seat_no": s["seat_no"],
            "remaining_ms": s["remaining_ms"],
            "connection_remaining_ms": s["connection_remaining_ms"],
            "connected": s["connected"],
        }
        for s in public["seats"]
    ]
    expires = None if finished else iso_utc(public.get("current_expires_at_ms"))
    return seats, expires


def last_action(hint: dict) -> Optional[dict]:
    """이벤트 hint → `turn_change.last_action`. 이동·벽만 행동이다"""
    action = hint.get("last_action") or {}
    if action.get("kind") not in ACTION_KINDS:
        return None
    return {"seat_no": action["seat_no"], "kind": action["kind"]}


def game_state_payload(view: dict) -> dict:
    """좌석별 화면(maze_view) → `game_state`. 시계만 와이어 모양으로 바꾼다"""
    payload = dict(view)
    payload["clocks"], payload["clock_expires_at"] = clocks_wire(view.get("clocks"), finished=view["finished"])
    return payload


def turn_change_payload(view: dict, hint: dict) -> dict:
    clocks, expires = clocks_wire(view.get("clocks"), finished=view["finished"])
    return {
        "current_seat_no": view["current_seat_no"],
        "turn_count": view["turn_count"],
        "last_action": last_action(hint),
        "clocks": clocks,
        "clock_expires_at": expires,
    }


def player_left_eliminated(seat_no: int, reason: Optional[str], survivor_count: int) -> dict:
    return {"seat_no": seat_no, "state": "eliminated", "reason": reason, "survivors": survivor_count}


def player_left_reconnecting(seat_no: int, grace_remaining_ms: int, survivor_count: int) -> dict:
    return {
        "seat_no": seat_no, "state": "reconnecting", "reason": None,
        "grace_remaining_ms": grace_remaining_ms, "survivors": survivor_count,
    }


def player_reconnected(seat_no: int) -> dict:
    return {"seat_no": seat_no, "state": "reconnected"}


def game_start_payload(meta: GameMeta, my_seat_no: Optional[int]) -> dict:
    return {
        "game_id": meta.game_id,
        "mode": meta.mode,
        "is_ranked": meta.is_ranked,
        "my_seat_no": my_seat_no,
        "players": [
            {"seat_no": p.seat_no, "nickname": p.nickname, "is_ai": p.is_ai} for p in meta.players
        ],
    }


def full_board(state: GameState, *, voided: bool = False) -> dict:
    """끝난(또는 무효 처리된) 게임의 최종 벽 배치와 위치. 경로·수 기록은 담지 않는다(§10)"""
    if not (state.is_finished or voided):
        raise ValueError("full_board is only for finished games")
    return {
        "walls": [w.to_dict() for w in state.wall_manager.walls],
        "final_positions": [
            {"seat_no": p.seat_no, "row": p.position.row, "col": p.position.col} for p in state.seats
        ],
    }


def _mmr_null() -> dict:
    return {"mmr_before": None, "mmr_after": None, "mmr_delta": None}


def game_end_payload(
    game_id: str,
    state: Optional[GameState],
    meta: Optional[GameMeta],
    *,
    voided: bool,
) -> dict:
    """`game_end`. 무효(server_fault)는 전원 void — state 를 잃었으면 full_board 는 null, 결과는 meta 좌석으로"""
    nicknames = {p.seat_no: p.nickname for p in meta.players} if meta is not None else {}
    if voided:
        seat_nos = [p.seat_no for p in state.seats] if state is not None else sorted(nicknames)
        results = [
            {
                "seat_no": s, "nickname": nicknames.get(s, ""), "rank": None, "result": RESULT_VOID,
                "elimination_reason": state.seat(s).elimination_reason if state is not None else None,
                **_mmr_null(),
            }
            for s in seat_nos
        ]
        return {
            "game_id": game_id,
            "reason": END_SERVER_FAULT,
            "results": results,
            "full_board": full_board(state, voided=True) if state is not None else None,
        }

    if state is None or not state.is_finished:
        raise ValueError("game_end needs a finished state")
    return {
        "game_id": game_id,
        "reason": state.end_reason.value,
        "results": [
            {
                "seat_no": r.seat_no, "nickname": nicknames.get(r.seat_no, ""), "rank": r.rank,
                "result": r.result, "elimination_reason": r.elimination_reason, **_mmr_null(),
            }
            for r in seat_results(state)
        ],
        "full_board": full_board(state),
    }


# ----- 큐·매치·방 (§3·§4) — user_id 는 와이어에 싣지 않는다 -----

def room_payload(snapshot: dict) -> dict:
    """events.room_snapshot → §4 방 페이로드. 좌석은 seat_no·닉네임·방장·준비만"""
    return {
        "room_code": snapshot["code"],
        "mode": snapshot["mode"],
        "capacity": snapshot["capacity"],
        "status": snapshot["status"],
        "allow_spectate": snapshot["allow_spectate"],
        "players": [
            {"seat_no": p["seat_no"], "nickname": p["nickname"],
             "is_host": p["is_host"], "is_ready": p["is_ready"]}
            for p in snapshot["players"]
        ],
    }


def matched_payload(match_id: str, hint: dict, my_seat_no: Optional[int], now_ms: int) -> dict:
    remaining_ms = max(0, hint["ready_deadline_ms"] - now_ms)
    return {
        "match_id": match_id,
        "mode": hint["mode"],
        "my_seat_no": my_seat_no,
        "players": [
            {"seat_no": p["seat_no"], "nickname": p["nickname"], "mmr": p.get("mmr")} for p in hint["players"]
        ],
        "ready_deadline_sec": -(-remaining_ms // 1000),
    }


def queue_payload(mode: str, position: int, waiting_count: int, **extra) -> dict:
    return {"mode": mode, "position": position, "waiting_count": waiting_count, **extra}
