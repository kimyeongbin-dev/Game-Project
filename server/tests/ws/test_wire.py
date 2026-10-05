"""§12 페이로드 빌더 — 순수 함수 (maze.md §5·§8·§10)"""

import pytest

from app.games.maze import GameState
from app.services.maze_game import GameMeta, SeatPlayer
from app.ws import wire


def _meta(state: GameState) -> GameMeta:
    return GameMeta(
        game_id=state.game_id, game="maze_1p", mode=state.mode, is_ranked=True, room_code=None,
        created_at="2026-10-05T00:00:00Z",
        players=tuple(SeatPlayer(p.seat_no, 100 + p.seat_no, f"n{p.seat_no}") for p in state.seats),
    )


def _finished_by_surrender(mode: str) -> GameState:
    state = GameState(mode)
    for p in state.seats[:-1]:
        state.eliminate(p.seat_no, "surrender")
    assert state.is_finished
    return state


def test_iso_utc_millis():
    assert wire.iso_utc(1_759_311_268_123) == "2025-10-01T09:34:28.123Z"
    assert wire.iso_utc(None) is None


def test_clocks_wire_shape_and_finished():
    public = {
        "seats": [{"seat_no": 1, "remaining_ms": 5, "connection_remaining_ms": 6, "connected": True}],
        "current_expires_at_ms": 1_759_311_268_000, "voided": False,
    }
    seats, expires = wire.clocks_wire(public, finished=False)
    assert seats == [{"seat_no": 1, "remaining_ms": 5, "connection_remaining_ms": 6, "connected": True}]
    assert expires == "2025-10-01T09:34:28.000Z"
    assert wire.clocks_wire(public, finished=True)[1] is None   # 끝난 게임은 소진 예정이 없다
    assert wire.clocks_wire(None, finished=False) == (None, None)


@pytest.mark.parametrize("hint, expected", [
    ({"last_action": {"seat_no": 2, "kind": "wall"}}, {"seat_no": 2, "kind": "wall"}),
    ({"last_action": {"seat_no": 2, "kind": "move", "extra": 1}}, {"seat_no": 2, "kind": "move"}),
    ({"last_action": {"seat_no": 2, "kind": "eliminated", "reason": "surrender"}}, None),
    ({}, None),
])
def test_last_action_is_move_or_wall_only(hint, expected):
    assert wire.last_action(hint) == expected


@pytest.mark.parametrize("mode", ["duel", "trio"])
def test_full_board_refuses_running_game(mode):
    """경기 중 전체 맵이 나갈 경로를 함수 수준에서 막는다 (§10)"""
    with pytest.raises(ValueError):
        wire.full_board(GameState(mode))
    with pytest.raises(ValueError):
        wire.game_end_payload("g", GameState(mode), None, voided=False)


@pytest.mark.parametrize("mode", ["duel", "trio"])
def test_game_end_finished(mode):
    state = _finished_by_surrender(mode)
    end = wire.game_end_payload(state.game_id, state, _meta(state), voided=False)
    assert end["reason"] == "last_standing"
    assert [r["rank"] for r in end["results"]][0] == 1
    assert {r["mmr_after"] for r in end["results"]} == {None}       # MMR 산정 전 (임시)
    assert {r["nickname"] for r in end["results"]} == {f"n{p.seat_no}" for p in state.seats}
    assert "user_id" not in str(end)
    assert len(end["full_board"]["final_positions"]) == len(state.seats)


def test_voided_keeps_board_when_state_survived():
    state = GameState("trio")   # 진행 중이었지만 장기 장애로 무효 — state 는 보존된다
    end = wire.game_end_payload(state.game_id, state, _meta(state), voided=True)
    assert end["reason"] == "server_fault"
    assert {r["result"] for r in end["results"]} == {"void"}
    assert {r["rank"] for r in end["results"]} == {None}
    assert end["full_board"] is not None


def test_voided_lost_state_has_no_board():
    state = GameState("duel")
    meta = _meta(state)
    end = wire.game_end_payload(state.game_id, None, meta, voided=True)
    assert end["full_board"] is None
    assert [r["seat_no"] for r in end["results"]] == [1, 2]
    assert wire.game_end_payload("gone", None, None, voided=True)["results"] == []


def test_room_payload_drops_user_id():
    snap = {"code": "K7QX2M", "game": "maze_1p", "mode": "trio", "capacity": 3, "status": "waiting",
            "allow_spectate": True,
            "players": [{"seat_no": 1, "user_id": 9, "nickname": "a", "is_host": True, "is_ready": False}]}
    out = wire.room_payload(snap)
    assert out["room_code"] == "K7QX2M" and out["allow_spectate"] is True
    assert "user_id" not in out["players"][0]


def test_matched_deadline_rounds_up():
    hint = {"mode": "duel", "ready_deadline_ms": 10_500,
            "players": [{"seat_no": 1, "user_id": 3, "nickname": "a", "mmr": 1000, "ready": False}]}
    out = wire.matched_payload("m1", hint, 1, now_ms=1_000)
    assert out["ready_deadline_sec"] == 10
    assert out["players"] == [{"seat_no": 1, "nickname": "a", "mmr": 1000}]
    assert wire.matched_payload("m1", hint, 1, now_ms=20_000)["ready_deadline_sec"] == 0
