"""
시야 엔진 테스트 — maze.md §6 (M3 5단계)

이산 규칙을 사용자 원 모델(내 칸 중심 반지름 1.25 의 원 + 벽 차폐)과 대조한다. 오라클은 P 기준 5×5 의
벽 자리(교차점 4×4 × 방향 2)에서 놓을 수 있는 벽 1·2개 조합만 본다 — 3×3 의 변에 걸칠 수 있는 벽은 거기뿐이다.
Redis·DB 를 쓰지 않는다.
"""

import itertools
import math
import random

import pytest

from app.games.maze import GameState
from app.games.maze.core.board import Board, Position
from app.games.maze.core.vision import (
    SeatMemory,
    UnitEdge,
    blocked_edges,
    edge_between,
    game_sight,
    sight,
    unit_edges,
)
from app.games.maze.core.wall import Orientation, Wall, WallManager

H, V = Orientation.HORIZONTAL, Orientation.VERTICAL
P = Position(4, 4)


def cell(dr: int, dc: int, origin: Position = P) -> Position:
    return Position(origin.row + dr, origin.col + dc)


# §6 그림의 칸 이름 (P 기준)
a, b, c = cell(-1, -1), cell(-1, 0), cell(-1, 1)
d, e = cell(0, -1), cell(0, 1)
f, g, h = cell(1, -1), cell(1, 0), cell(1, 1)


def E(x: Position, y: Position) -> UnitEdge:
    return edge_between(x, y)


# ----- §6 예시 -----

def test_example_1_one_orthogonal_side_blocked():
    """P｜b 에만 벽 — b 만 안 보이고, a·c 는 d·e 경유로 보인다"""
    s = sight(P, {E(P, b)})

    assert s.cells == {P, a, c, d, e, f, g, h}
    assert s.edges == {
        E(P, b): True, E(P, d): False, E(P, e): False, E(P, g): False,
        E(d, a): False, E(d, f): False,
        E(e, c): False, E(e, h): False,
        E(g, f): False, E(g, h): False,
    }
    # b 가 안 보여서 b 의 옆 변은 전송하지 않는다 (a 가 보여도)
    assert E(a, b) not in s.edges and E(b, c) not in s.edges


def test_example_2_diagonal_fully_blocked():
    """P｜b, P｜e 가 둘 다 막혔다 — c 는 두 경로가 모두 막혀 안 보이고, h 는 g 경유로 보인다"""
    s = sight(P, {E(P, b), E(P, e)})

    assert s.cells == {P, a, d, f, g, h}
    assert s.edges == {
        E(P, b): True, E(P, e): True, E(P, d): False, E(P, g): False,
        E(d, a): False, E(d, f): False, E(g, f): False, E(g, h): False,
    }
    assert E(e, h) not in s.edges and E(e, c) not in s.edges and E(b, c) not in s.edges


def test_half_wall_shows_only_the_visible_unit_edge():
    """2칸 벽의 반만 시야에 들면 그 단위 변 하나만 나온다"""
    wall = Wall(4, 5, H)          # (5,5) 북쪽 = e｜h, (5,6) 북쪽 = 3×3 밖
    inside, outside = unit_edges(wall)
    s = sight(P, blocked_edges([wall]))

    assert inside == E(e, h) and s.edges[inside] is True
    assert outside not in s.edges


# ----- 원 모델 오라클 -----

RADIUS = 1.25
SAMPLES = 8


def _segment(edge: UnitEdge):
    """단위 변의 양 끝점 (x=col, y=row 축, 칸 (r,c) 는 [c,c+1]×[r,r+1])"""
    if edge.orientation == H:
        return (edge.col, edge.row), (edge.col + 1, edge.row)
    return (edge.col, edge.row), (edge.col, edge.row + 1)


def _cross(o, p, q) -> float:
    return (p[0] - o[0]) * (q[1] - o[1]) - (p[1] - o[1]) * (q[0] - o[0])


def _crosses(p1, p2, q1, q2) -> bool:
    """두 선분이 끝점이 아닌 곳에서 교차한다"""
    d1, d2 = _cross(q1, q2, p1), _cross(q1, q2, p2)
    d3, d4 = _cross(p1, p2, q1), _cross(p1, p2, q2)
    return d1 * d2 < 0 and d3 * d4 < 0


def _internal_edges(origin: Position) -> list[UnitEdge]:
    """3×3 내부 변 중 보드 안의 것 (최대 12)"""
    found = set()
    for dr, dc in itertools.product((-1, 0, 1), repeat=2):
        x = (origin.row + dr, origin.col + dc)
        if not Board.is_valid_cell(*x):
            continue
        for nr, nc in ((x[0] + 1, x[1]), (x[0], x[1] + 1)):
            if abs(nr - origin.row) <= 1 and abs(nc - origin.col) <= 1 and Board.is_valid_cell(nr, nc):
                found.add(edge_between(Position(*x), Position(nr, nc)))
    return sorted(found, key=UnitEdge.sort_key)


def _usable(center, point) -> bool:
    """반지름 안이고, 시선이 P 의 모서리(격자점)를 정확히 지나지 않는다 — 측도 0 인 퇴화 시선 제외"""
    dx, dy = point[0] - center[0], point[1] - center[1]
    return math.hypot(dx, dy) < RADIUS and abs(abs(dx) - abs(dy)) > 1e-9


def oracle(origin: Position, blocked: set[UnitEdge]) -> tuple[set[Position], set[UnitEdge]]:
    """원 모델 그대로: 시선이 벽 변을 하나도 지나지 않고 닿는 표본이 있으면 보인다"""
    center = (origin.col + 0.5, origin.row + 0.5)
    internal = _internal_edges(origin)
    segments = {edge: _segment(edge) for edge in internal}

    def clear(point, own=None) -> bool:
        return not any(
            edge in blocked and edge != own and _crosses(center, point, *segments[edge])
            for edge in internal
        )

    cells, edges = set(), set()
    for dr, dc in itertools.product((-1, 0, 1), repeat=2):
        row, col = origin.row + dr, origin.col + dc
        if not Board.is_valid_cell(row, col):
            continue
        points = [
            (col + (i + 0.5) / SAMPLES, row + (j + 0.5) / SAMPLES)
            for i in range(SAMPLES) for j in range(SAMPLES)
        ]
        if any(_usable(center, pt) and clear(pt) for pt in points):
            cells.add(Position(row, col))
    for edge, (p1, p2) in segments.items():
        points = [
            (p1[0] + (p2[0] - p1[0]) * (k + 0.5) / SAMPLES, p1[1] + (p2[1] - p1[1]) * (k + 0.5) / SAMPLES)
            for k in range(SAMPLES)
        ]
        if any(_usable(center, pt) and clear(pt, own=edge) for pt in points):
            edges.add(edge)
    return cells, edges


def wall_slots_5x5(origin: Position) -> list[Wall]:
    """P 기준 5×5 안의 벽 자리 — 교차점 4×4 × 방향 2 중 보드 안의 것"""
    return [
        Wall(r, col, o)
        for r in range(origin.row - 2, origin.row + 2)
        for col in range(origin.col - 2, origin.col + 2)
        for o in (H, V)
        if Board.is_valid_wall_position(r, col)
    ]


def placeable(walls) -> bool:
    manager = WallManager()
    return all(manager.add_wall(w) for w in walls)


def assert_matches_oracle(origin: Position, walls) -> None:
    blocked = set(blocked_edges(walls))
    s = sight(origin, blocked)
    cells, edges = oracle(origin, blocked)
    assert s.cells == cells, (origin, walls)
    assert set(s.edges) == edges, (origin, walls)
    assert all(s.edges[edge] == (edge in blocked) for edge in s.edges)


def test_matches_circle_model_one_and_two_walls():
    slots = wall_slots_5x5(P)
    assert len(slots) == 32
    assert_matches_oracle(P, [])
    for wall in slots:
        assert_matches_oracle(P, [wall])
    pairs = [pair for pair in itertools.combinations(slots, 2) if placeable(pair)]
    assert len(pairs) > 400
    for pair in pairs:
        assert_matches_oracle(P, pair)


@pytest.mark.parametrize("origin", [Position(0, 0), Position(8, 8), Position(8, 4), Position(4, 0)])
def test_matches_circle_model_at_board_edges(origin):
    assert_matches_oracle(origin, [])
    for wall in wall_slots_5x5(origin):
        assert_matches_oracle(origin, [wall])


def test_corner_has_no_border_edges():
    s = sight(Position(0, 0), set())
    assert s.cells == {Position(0, 0), Position(0, 1), Position(1, 0), Position(1, 1)}
    assert set(s.edges) == {
        UnitEdge(0, 1, V), UnitEdge(1, 0, H),   # P 의 보드 안 2면
        UnitEdge(1, 1, H), UnitEdge(1, 1, V),   # (0,1)·(1,0) 의 옆 변
    }


@pytest.mark.parametrize("origin", [P, Position(0, 0), Position(8, 4)])
def test_never_outer_border_and_always_my_sides(origin):
    """3×3 외곽 변은 어떤 배치에서도 나오지 않고, 보드 안의 내 4면은 언제나 나온다"""
    internal = set(_internal_edges(origin))
    mine = {
        edge_between(origin, n) for n in Board.get_adjacent_positions(origin)
    }
    for wall in [None, *wall_slots_5x5(origin)]:
        s = sight(origin, blocked_edges([wall] if wall else []))
        assert set(s.edges) <= internal
        assert mine <= set(s.edges)


# ----- 2칸 벽 ↔ 단위 변 ↔ 엔진 -----

def _all_walls() -> list[Wall]:
    return [Wall(r, col, o) for r in range(8) for col in range(8) for o in (H, V)]


def _adjacent_pairs():
    for row in range(Board.SIZE):
        for col in range(Board.SIZE):
            here = Position(row, col)
            for n in Board.get_adjacent_positions(here):
                yield here, n


def test_unit_edges_match_engine_blocking_and_slots():
    """시야와 이동·설치 판정이 같은 변을 본다 (128 벽 자리 전부)"""
    pairs = list(_adjacent_pairs())
    for wall in _all_walls():
        manager = WallManager()
        manager.add_wall(wall)
        edges = set(unit_edges(wall))
        for x, y in pairs:
            assert manager.is_move_blocked(x, y) == (edge_between(x, y) in edges), (wall, x, y)

        slots = {s for s in wall.get_occupied_slots() if s[2] != "center"}
        as_edges = {
            UnitEdge(r + 1, col, H) if kind == "h" else UnitEdge(r, col + 1, V)
            for r, col, kind in slots
        }
        assert as_edges == edges


@pytest.mark.parametrize("orientation", [H, V])
def test_wall_needs_both_unit_edges_free(orientation):
    """한 변만 남은 자리에는 놓을 수 없다 — 엔진 동작 고정 (규칙 변경 없음)"""
    manager = WallManager()
    assert manager.add_wall(Wall(3, 3, orientation))
    shift = (0, 1) if orientation == H else (1, 0)
    for sign in (1, -1):
        half_overlap = Wall(3 + sign * shift[0], 3 + sign * shift[1], orientation)
        assert manager.can_place_wall(half_overlap) is False
    clear = Wall(3 + 2 * shift[0], 3 + 2 * shift[1], orientation)
    assert manager.can_place_wall(clear) is True
    # 같은 교차점에서 X 자로 가로지르는 벽도 막힌다 (단위 변은 공유하지 않는다)
    crossing = Wall(3, 3, V if orientation == H else H)
    assert not set(unit_edges(crossing)) & set(unit_edges(Wall(3, 3, orientation)))
    assert manager.can_place_wall(crossing) is False


def test_board_end_leaves_no_half_wall():
    """보드 끝에서 변 하나만 남는 자리는 좌표 범위가 막는다"""
    with pytest.raises(ValueError):
        Wall(3, 8, H)
    with pytest.raises(ValueError):
        Wall(8, 3, V)


# ----- 말 -----

def test_overlapping_pieces_each_listed():
    others = [(2, b), (3, b), (4, P), (5, cell(-2, 0))]
    s = sight(P, set(), others)
    assert s.players == ((2, b), (3, b), (4, P))


def test_piece_behind_wall_is_hidden_but_on_my_cell_is_seen():
    s = sight(P, {E(P, b)}, [(2, b), (3, P)])
    assert s.players == ((3, P),)


def test_eliminated_piece_is_still_seen():
    state = GameState("trio", rng=random.Random(1))
    state.seat(2).move_to(Board.get_adjacent_positions(state.seat(1).position)[0])
    state.eliminate(2, "surrender")
    assert 2 in {seat for seat, _ in game_sight(state, 1).players}


# ----- 누적 -----

def test_memory_edges_only_go_open_to_wall():
    edge = E(P, b)
    open_view = sight(P, set())
    walled_view = sight(P, {edge})

    m = SeatMemory().observe(open_view, 0)
    assert m.edges[edge] is False
    m = m.observe(walled_view, 1)
    assert m.edges[edge] is True
    m = m.observe(open_view, 2)          # 벽은 사라지지 않는다
    assert m.edges[edge] is True


def test_memory_keeps_last_seen_out_of_sight():
    m = SeatMemory().observe(sight(P, set(), [(2, b)]), 3)
    m = m.observe(sight(P, set(), [(2, cell(-3, 0))]), 4)   # 시야 밖으로 나갔다
    assert m.last_seen == {2: (b, 3)}
    m = m.observe(sight(P, set(), [(2, c)]), 5)
    assert m.last_seen == {2: (c, 5)}


def test_memory_round_trip_and_version():
    m = SeatMemory().observe(sight(P, {E(P, b)}, [(2, a), (3, a)]), 7)
    assert SeatMemory.from_dict(m.to_dict()) == m
    data = m.to_dict()
    data["v"] = 999
    with pytest.raises(ValueError):
        SeatMemory.from_dict(data)


# ----- 무작위 대국 불변식 -----

GAMES = 10
MAX_ACTIONS = 60


def _random_action(state: GameState, rng: random.Random) -> None:
    seat = state.current_seat_no
    if rng.random() < 0.3 and state.place_wall(
        seat, rng.randrange(8), rng.randrange(8), rng.choice(("horizontal", "vertical"))
    ) is None:
        return
    target = rng.choice(state.get_valid_pawn_moves())
    assert state.move(seat, target.row, target.col) is None


def test_random_games_keep_invariants(seat_mode):
    """매 수 후 좌석마다: 발견 ⊇ 지금 시야, 벽 표시는 진실, last_seen 은 그 턴의 실제 위치이고
    시야 밖 좌석의 last_seen 은 바뀌지 않는다 (§6 MUST NOT — 목격하지 않은 것을 채우지 않는다)"""
    mode, seats = seat_mode
    for seed in range(GAMES):
        rng = random.Random(seed)
        state = GameState(mode, rng=rng)
        memories = {p.seat_no: SeatMemory().observe(game_sight(state, p.seat_no), 0) for p in state.seats}
        history = {0: {p.seat_no: p.position for p in state.seats}}

        for _ in range(MAX_ACTIONS):
            if state.is_finished:
                break
            _random_action(state, rng)
            history[state.turn_count] = {p.seat_no: p.position for p in state.seats}
            blocked = blocked_edges(state.wall_manager.walls)

            for seat_no, before in memories.items():
                now = game_sight(state, seat_no)
                after = before.observe(now, state.turn_count)
                memories[seat_no] = after

                me = state.seat(seat_no).position
                assert all(abs(x.row - me.row) <= 1 and abs(x.col - me.col) <= 1 for x in now.cells)
                assert {s for s, pos in now.players} == {
                    p.seat_no for p in state.seats if p.seat_no != seat_no and p.position in now.cells
                }
                for edge, wall in now.edges.items():
                    assert after.edges[edge] == wall == (edge in blocked)
                for edge, wall in after.edges.items():
                    if wall:
                        assert edge in blocked                      # 본 벽은 진짜다
                for other, (pos, turn) in after.last_seen.items():
                    assert history[turn][other] == pos              # 목격한 그 턴의 실제 위치
                seen_now = {s for s, _ in now.players}
                for other, record in before.last_seen.items():
                    if other not in seen_now:
                        assert after.last_seen[other] == record     # 시야 밖이면 그대로
