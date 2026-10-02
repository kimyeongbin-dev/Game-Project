"""
Vision Module
3×3 시야 + 벽 차폐 (docs/api/games/maze.md §6)

시야 모델: 칸을 1×1 정사각형으로 볼 때, 내 칸 중심에서 반지름 1.25 의 원. 벽은 그 뒤를 가린다.
아래 이산 규칙이 그 정확한 이산화다(P = 내 칸).

- 직교 칸 X 는 `P｜X` 에 벽이 없으면 보인다
- 대각 칸 D 는 D 에 붙은 직교 칸 X 중 하나라도 **보이고** `X｜D` 에 벽이 없으면 보인다
- 보이는 변: P 의 4면(벽이든 아니든 항상) + **보이는 직교 칸** X 의 옆 변 `X｜D`. 대각 칸 쪽에서는 변이 보이지 않는다
- 3×3 의 바깥 테두리는 반지름 밖이라 절대 보이지 않는다. 보드 테두리는 변이 아니다
- 말은 그 칸이 보이면 보인다 (일부만 보여도)

관측 단위는 2칸 벽이 아니라 **단위 변**이다. 벽의 반만 보이면 반만 보인다.

이 모듈은 저장소를 모른다. 누적 상태(`SeatMemory`)의 저장은 app/services/maze_game.py 몫이다.
"""

from dataclasses import dataclass, field
from typing import AbstractSet, Iterable

from .board import Board, Position
from .wall import Orientation, Wall

# SeatMemory.to_dict() 형태가 바뀌면 올린다
VISION_SCHEMA_VERSION = 1

_ORTHOGONAL = ((-1, 0), (1, 0), (0, -1), (0, 1))
_CODE = {Orientation.HORIZONTAL: "h", Orientation.VERTICAL: "v"}
_FROM_CODE = {code: o for o, code in _CODE.items()}


@dataclass(frozen=True)
class UnitEdge:
    """관측 단위 변 — 칸 기준 (§6 좌표 규약)

    horizontal = 칸 (row, col) 의 북쪽 변 (1 ≤ row ≤ 8)
    vertical   = 칸 (row, col) 의 서쪽 변 (1 ≤ col ≤ 8)
    """
    row: int
    col: int
    orientation: Orientation

    def sort_key(self) -> tuple[int, int, str]:
        return (self.row, self.col, self.orientation.value)

    def to_dict(self, wall: bool) -> dict:
        return {
            "row": self.row,
            "col": self.col,
            "orientation": self.orientation.value,
            "wall": wall,
        }


def unit_edges(wall: Wall) -> tuple[UnitEdge, UnitEdge]:
    """2칸 벽(교차점 기준) → 단위 변 2개(칸 기준)"""
    r, c = wall.row, wall.col
    if wall.orientation == Orientation.HORIZONTAL:
        return (
            UnitEdge(r + 1, c, Orientation.HORIZONTAL),
            UnitEdge(r + 1, c + 1, Orientation.HORIZONTAL),
        )
    return (
        UnitEdge(r, c + 1, Orientation.VERTICAL),
        UnitEdge(r + 1, c + 1, Orientation.VERTICAL),
    )


def edge_between(a: Position, b: Position) -> UnitEdge:
    """직교 인접한 두 칸의 경계 변. 인접하지 않으면 ValueError"""
    dr, dc = b.row - a.row, b.col - a.col
    if dc == 0 and abs(dr) == 1:
        return UnitEdge(max(a.row, b.row), a.col, Orientation.HORIZONTAL)
    if dr == 0 and abs(dc) == 1:
        return UnitEdge(a.row, max(a.col, b.col), Orientation.VERTICAL)
    raise ValueError("cells are not orthogonally adjacent")


@dataclass(frozen=True)
class Sight:
    """지금 이 순간 보이는 것"""
    cells: frozenset[Position]
    edges: dict[UnitEdge, bool]                  # 변 → 벽 여부
    players: tuple[tuple[int, Position], ...]    # (seat_no, 위치), seat_no 오름차순


def _neighbor(pos: Position, dr: int, dc: int):
    row, col = pos.row + dr, pos.col + dc
    return Position(row, col) if Board.is_valid_cell(row, col) else None


def sight(
    origin: Position,
    blocked: AbstractSet[UnitEdge],
    others: Iterable[tuple[int, Position]] = (),
) -> Sight:
    """origin 에서 보이는 칸·변·말. blocked = 벽이 있는 단위 변 집합"""
    cells = {origin}
    edges: dict[UnitEdge, bool] = {}

    for dr, dc in _ORTHOGONAL:
        side = _neighbor(origin, dr, dc)
        if side is None:
            continue
        edge = edge_between(origin, side)
        edges[edge] = edge in blocked
        if edge in blocked:
            continue
        cells.add(side)
        # 보이는 직교 칸의 옆 변 → 그 너머 대각 칸
        for pr, pc in ((0, -1), (0, 1)) if dr else ((-1, 0), (1, 0)):
            corner = _neighbor(side, pr, pc)
            if corner is None:
                continue
            ring = edge_between(side, corner)
            edges[ring] = ring in blocked
            if ring not in blocked:
                cells.add(corner)

    players = tuple(sorted(
        ((seat_no, pos) for seat_no, pos in others if pos in cells),
        key=lambda p: p[0],
    ))
    return Sight(frozenset(cells), edges, players)


def blocked_edges(walls: Iterable[Wall]) -> frozenset[UnitEdge]:
    """설치된 벽 전부 → 벽이 있는 단위 변 집합"""
    return frozenset(edge for wall in walls for edge in unit_edges(wall))


def game_sight(state, seat_no: int) -> Sight:
    """게임 상태에서 seat_no 의 현재 시야. 다른 좌석의 말은 탈락자도 보인다(§9)"""
    me = state.seat(seat_no)
    return sight(
        me.position,
        blocked_edges(state.wall_manager.walls),
        ((p.seat_no, p.position) for p in state.seats if p.seat_no != seat_no),
    )


@dataclass(frozen=True)
class SeatMemory:
    """좌석의 누적 관측 — 발견 맵과 마지막 목격 (§6)

    edges: 한 번이라도 본 변 → 마지막으로 본 벽 여부. 미발견 → 열림 → 벽 으로만 바뀐다
    last_seen: seat_no → (목격 위치, 목격 턴). 시야 밖 이동으로는 바뀌지 않는다
    """
    edges: dict[UnitEdge, bool] = field(default_factory=dict)
    last_seen: dict[int, tuple[Position, int]] = field(default_factory=dict)

    def observe(self, seen: Sight, turn: int) -> "SeatMemory":
        edges = dict(self.edges)
        for edge, wall in seen.edges.items():
            edges[edge] = wall or edges.get(edge, False)  # 벽은 사라지지 않는다
        last_seen = dict(self.last_seen)
        for seat_no, pos in seen.players:
            last_seen[seat_no] = (pos, turn)
        return SeatMemory(edges, last_seen)

    def to_dict(self) -> dict:
        return {
            "v": VISION_SCHEMA_VERSION,
            "edges": [
                [e.row, e.col, _CODE[e.orientation], wall]
                for e, wall in sorted(self.edges.items(), key=lambda kv: kv[0].sort_key())
            ],
            "last_seen": [
                {"seat_no": seat_no, "row": pos.row, "col": pos.col, "turn": turn}
                for seat_no, (pos, turn) in sorted(self.last_seen.items())
            ],
        }

    @classmethod
    def from_dict(cls, data: dict) -> "SeatMemory":
        """to_dict() 결과에서 복원. 버전이 다르면 ValueError"""
        if data.get("v") != VISION_SCHEMA_VERSION:
            raise ValueError(f"Unsupported vision schema version: {data.get('v')}")
        return cls(
            {UnitEdge(r, c, _FROM_CODE[o]): bool(w) for r, c, o, w in data["edges"]},
            {
                s["seat_no"]: (Position(s["row"], s["col"]), s["turn"])
                for s in data["last_seen"]
            },
        )


def edges_payload(edges: dict[UnitEdge, bool]) -> list[dict]:
    """변 → 패킷 원소 목록 `{row, col, orientation, wall}` (결정적 순서)"""
    return [e.to_dict(wall) for e, wall in sorted(edges.items(), key=lambda kv: kv[0].sort_key())]
