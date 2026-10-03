"""
게임 시계 · 접속 시계 순수 계산 (maze.md §8·§9, M3 6단계 커밋 1)

Redis·DB 없이 돈다. 시각은 숫자로 넘긴다 — 실제 시간을 기다리지 않는다.
"""

import pytest

from app.services.maze_clock import (
    DISCONNECT_FORFEIT,
    TIME_FORFEIT,
    GameClocks,
    charged,
    expiry_at,
    merge,
)

T0 = 1_000_000
S = 1_000  # 1초
INITIAL = 300 * S
INCREMENT = 5 * S
BUDGET = 60 * S
GRACE = 30 * S


def start(seats=(1, 2), now=T0) -> GameClocks:
    return GameClocks.start(seats, now, initial_ms=INITIAL, budget_ms=BUDGET)


# ----- 구간 산술 -----

def test_merge_unions_overlaps_and_drops_empty():
    assert merge([(5, 10), (0, 3), (8, 12), (3, 4), (7, 7)]) == [(0, 4), (5, 12)]


def test_charged_subtracts_only_overlap():
    exempt = merge([(10, 20), (30, 40)])
    assert charged(0, 50, exempt) == 30
    assert charged(15, 35, exempt) == 10   # 부분 겹침 양쪽
    assert charged(50, 60, exempt) == 10   # 겹침 없음
    assert charged(12, 18, exempt) == 0    # 완전히 면제
    assert charged(20, 10, exempt) == 0    # 거꾸로


def test_expiry_at_skips_exempt_windows():
    exempt = merge([(10, 20)])
    assert expiry_at(0, 5, exempt) == 5        # 면제 전에 끝난다
    assert expiry_at(0, 15, exempt) == 25      # 면제 10 만큼 밀린다
    assert expiry_at(12, 5, exempt) == 25      # 면제 안에서 시작
    assert expiry_at(0, 0, exempt) == 0
    for budget in (1, 9, 10, 11, 30):          # 정의: charged(start, T) == budget 인 가장 이른 T
        t = expiry_at(0, budget, exempt)
        assert charged(0, t, exempt) == budget
        assert charged(0, t - 1, exempt) < budget


# ----- Fischer -----

def test_fischer_charges_elapsed_and_adds_increment():
    c = start()
    c.close_turn(1, T0 + 10 * S, increment_ms=INCREMENT)
    assert c.seat(1).remaining_ms == INITIAL - 10 * S + INCREMENT
    assert c.turn_started_at_ms == T0 + 10 * S


def test_game_clock_runs_only_on_own_turn():
    c = start()
    later = T0 + 42 * S
    assert c.game_remaining(1, 1, later) == INITIAL - 42 * S
    assert c.game_remaining(2, 1, later) == INITIAL       # 차례가 아니다


def test_rejected_attempt_changes_nothing_but_time_keeps_running():
    """거절은 정산하지 않는다 — 저장값 그대로, 잔량은 경과만큼 준다(§8)"""
    c = start()
    before = c.to_dict()
    assert c.game_remaining(1, 1, T0 + 7 * S) == INITIAL - 7 * S
    assert c.to_dict() == before


# ----- 두 시계 분리 -----

def test_disconnected_on_own_turn_loses_both_clocks():
    c = start()
    c.disconnect(1, T0 + 10 * S)
    t = T0 + 30 * S
    assert c.game_remaining(1, 1, t) == INITIAL - 30 * S
    assert c.conn_remaining(1, t) == BUDGET - 20 * S


def test_disconnected_off_turn_loses_only_connection_clock():
    c = start()
    c.disconnect(2, T0)
    t = T0 + 20 * S
    assert c.game_remaining(2, 1, t) == INITIAL
    assert c.conn_remaining(2, t) == BUDGET - 20 * S


def test_connection_clock_accumulates_and_never_resets():
    c = start()
    total = 0
    t = T0
    for gap in (3, 10, 1, 7):
        c.disconnect(2, t)
        t += gap * S
        c.reconnect(2, 1, t)
        total += gap * S
        t += 50 * S  # 연결된 동안은 흐르지 않는다
    assert c.seat(2).conn_remaining_ms == BUDGET - total


def test_disconnect_twice_keeps_first_start():
    c = start()
    assert c.disconnect(2, T0)
    assert not c.disconnect(2, T0 + 10 * S)
    assert c.seat(2).disconnected_at_ms == T0


def test_reconnect_while_connected_is_noop():
    c = start()
    assert not c.reconnect(2, 1, T0 + S)
    assert c.seat(2).conn_remaining_ms == BUDGET


# ----- 면제 (서버 유예 · 장애 구간) -----

def test_server_grace_freezes_both_clocks_up_to_cap():
    c = start()
    d = T0 + 10 * S
    c.disconnect(1, d)
    assert c.apply_grace(1, d, GRACE)
    inside = d + 20 * S
    assert c.conn_remaining(1, inside) == BUDGET
    assert c.game_remaining(1, 1, inside) == INITIAL - 10 * S
    after = d + 45 * S
    assert c.conn_remaining(1, after) == BUDGET - 15 * S
    assert c.game_remaining(1, 1, after) == INITIAL - 10 * S - 15 * S


def test_reconnect_cuts_server_grace_window():
    c = start()
    d = T0 + 10 * S
    c.disconnect(1, d)
    c.apply_grace(1, d, GRACE)
    c.reconnect(1, 1, d + 5 * S)
    assert c.seat(1).conn_remaining_ms == BUDGET           # 유예 안의 끊김은 무료
    t = d + 40 * S
    assert c.game_remaining(1, 1, t) == INITIAL - (t - T0) + 5 * S  # 면제는 5 s 뿐


def test_apply_grace_requires_same_disconnection():
    c = start()
    c.disconnect(2, T0)
    assert not c.apply_grace(2, T0 + 1, GRACE)     # 다른 끊김
    assert c.apply_grace(2, T0, GRACE)
    assert not c.apply_grace(2, T0, GRACE)         # 두 번 걸지 않는다
    c.reconnect(2, 1, T0 + S)
    assert not c.apply_grace(2, T0, GRACE)         # 이미 재접속


def test_outage_is_exempt_for_both_clocks():
    c = start()
    c.disconnect(1, T0)
    outages = [(T0 + 10 * S, T0 + 40 * S)]
    t = T0 + 50 * S
    assert c.game_remaining(1, 1, t, outages) == INITIAL - 20 * S
    assert c.conn_remaining(1, t, outages) == BUDGET - 20 * S


def test_grace_and_outage_overlap_count_once():
    c = start()
    c.disconnect(1, T0)
    c.apply_grace(1, T0, GRACE)                    # [T0, T0+30)
    outages = [(T0 + 20 * S, T0 + 50 * S)]         # 겹침 10 s
    t = T0 + 60 * S
    assert c.conn_remaining(1, t, outages) == BUDGET - 10 * S


# ----- 데드라인 -----

def test_deadlines_match_actual_exhaustion():
    c = start()
    c.disconnect(2, T0 + 5 * S)
    outages = [(T0 + 100 * S, T0 + 110 * S)]
    due = c.deadlines(1, outages)
    assert due.clock_at == T0 + INITIAL + 10 * S
    assert due.grace_at == {2: T0 + 5 * S + BUDGET}
    assert c.game_remaining(1, 1, due.clock_at, outages) == 0
    assert c.conn_remaining(2, due.grace_at[2], outages) == 0


def test_deadlines_exclude_frozen_connected_and_stopped():
    c = start((1, 2, 3))
    c.disconnect(2, T0)
    c.disconnect(3, T0)
    c.freeze(3, T0 + S)
    due = c.deadlines(1)
    assert set(due.grace_at) == {2}
    assert due.clock_at is not None
    c.stop(T0 + 2 * S)
    assert c.deadlines(1) == type(due)(None, {})


def test_frozen_current_seat_has_no_clock_deadline():
    c = start()
    c.freeze(1, T0)
    assert c.deadlines(1).clock_at is None


# ----- 정산 -----

def test_settle_orders_by_exhaustion_time_then_seat():
    c = start((1, 2, 3, 4))
    c.disconnect(3, T0)
    c.disconnect(2, T0 + S)
    c.disconnect(4, T0)
    now = T0 + BUDGET + 10 * S
    got = c.settle(1, now)
    assert [(e.seat_no, e.reason) for e in got] == [
        (3, DISCONNECT_FORFEIT), (4, DISCONNECT_FORFEIT), (2, DISCONNECT_FORFEIT),
    ]
    assert [e.at_ms for e in got] == [T0 + BUDGET, T0 + BUDGET, T0 + S + BUDGET]


def test_settle_reports_earliest_clock_once_per_seat():
    c = start()
    c.disconnect(1, T0)                 # 접속 시계가 게임 시계보다 먼저 0
    got = c.settle(1, T0 + INITIAL + S)
    assert [(e.seat_no, e.reason, e.at_ms) for e in got] == [(1, DISCONNECT_FORFEIT, T0 + BUDGET)]


def test_settle_before_exhaustion_is_empty_and_pure():
    c = start()
    before = c.to_dict()
    assert c.settle(1, T0 + INITIAL - 1) == []
    assert [e.reason for e in c.settle(1, T0 + INITIAL)] == [TIME_FORFEIT]
    assert c.to_dict() == before


def test_next_seat_starts_at_processing_time_after_time_forfeit():
    """감지 지연을 다음 좌석에 물리지 않는다 — 다음 차례는 처리 시각부터"""
    c = start()
    late = T0 + INITIAL + 20 * S
    assert [e.seat_no for e in c.settle(1, late)] == [1]
    c.close_turn(1, late)
    c.freeze(1, late)
    c.begin_turn(late)
    assert c.game_remaining(2, 2, late) == INITIAL
    assert c.settle(2, late) == []


def test_freeze_settles_connection_clock():
    c = start()
    c.disconnect(2, T0)
    c.freeze(2, T0 + 10 * S)
    assert c.seat(2).conn_remaining_ms == BUDGET - 10 * S
    assert c.conn_remaining(2, T0 + 100 * S) == BUDGET - 10 * S


# ----- 공개·직렬화 -----

def test_public_view_clamps_and_reports_current_deadline():
    c = start()
    c.disconnect(2, T0)
    view = c.public_view(1, T0 + 400 * S)
    assert view["current_expires_at_ms"] == T0 + INITIAL
    assert view["seats"][0] == {"seat_no": 1, "remaining_ms": 0,
                                "connection_remaining_ms": BUDGET, "connected": True}
    assert view["seats"][1]["connection_remaining_ms"] == 0
    assert view["seats"][1]["connected"] is False


def test_roundtrip_and_version_guard():
    c = start((1, 2, 3))
    c.disconnect(2, T0)
    c.apply_grace(2, T0, GRACE)
    c.close_turn(1, T0 + S, increment_ms=INCREMENT)
    assert GameClocks.from_dict(c.to_dict()) == c
    data = c.to_dict()
    data["v"] = 999
    with pytest.raises(ValueError):
        GameClocks.from_dict(data)


# ----- N인 -----

def test_rotation_over_n_seats(seat_mode):
    """좌석마다 자기 차례에 쓴 시간만 차감된다 — 인원 수와 무관"""
    _, seats = seat_mode
    c = start(range(1, seats + 1))
    t = T0
    for rnd in range(2):
        for seat_no in range(1, seats + 1):
            t += seat_no * S
            c.close_turn(seat_no, t, increment_ms=INCREMENT)
    for seat_no in range(1, seats + 1):
        assert c.seat(seat_no).remaining_ms == INITIAL - 2 * seat_no * S + 2 * INCREMENT
    c.disconnect(seats, t)
    due = c.deadlines(1)
    assert set(due.grace_at) == {seats}
    assert due.clock_at == t + c.seat(1).remaining_ms
