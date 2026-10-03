"""
게임 시계 · 접속 시계 — 순수 계산 (docs/api/games/maze.md §8·§9, M3 6단계)

두 시계를 완전히 분리한다.

| | 게임 시계 (Fischer) | 접속 시계 |
| :-- | :-- | :-- |
| 흐르는 조건 | 자기 차례일 때만 | 연결이 끊긴 동안만 (차례와 무관) |
| 갱신 | 행동 수락 시 경과 차감 + 증분 | 재접속 시 끊긴 구간 차감. **리셋 없음** |
| 소진 | `time_forfeit` | `disconnect_forfeit` |

**지연 정산.** 저장하는 것은 마지막 정산 시점의 잔량과 "흐르기 시작한 시각"뿐이다. 임의 시각 t 의 잔량은
`잔량 − charged(시작, t)` 이고, `charged` 는 경과에서 **면제 구간**(그 좌석의 서버 유예 ∪ 전역 Redis 장애 구간)을 뺀 값이다.
그래서 서버 유예를 끊김 뒤에 소급해 걸어도, 장애 구간이 나중에 기록돼도 결과가 정확하다.

이 모듈은 저장소·시각 출처를 모른다. 시각(`now`)은 호출자가 Redis TIME 으로 읽어 넘기고(app/core/time.py),
저장(`game:{id}:clocks`)과 데드라인 ZSET 갱신은 app/services/maze_game.py 가 게임 락 안에서 한다.
인원 수를 쓰지 않는다 — 좌석 목록에서 만든다.
"""

from dataclasses import dataclass, field
from typing import Iterable, Optional, Sequence

# GameClocks.to_dict() 형태가 바뀌면 올린다
CLOCKS_SCHEMA_VERSION = 1

TIME_FORFEIT = "time_forfeit"
DISCONNECT_FORFEIT = "disconnect_forfeit"

Interval = tuple[int, int]  # [시작, 끝) epoch ms


def merge(intervals: Iterable[Interval]) -> list[Interval]:
    """겹치거나 맞닿은 구간을 합친다. 빈 구간은 버린다"""
    out: list[list[int]] = []
    for start, end in sorted(i for i in intervals if i[1] > i[0]):
        if out and start <= out[-1][1]:
            out[-1][1] = max(out[-1][1], end)
        else:
            out.append([start, end])
    return [(s, e) for s, e in out]


def charged(start: int, end: int, exempt: Sequence[Interval]) -> int:
    """[start, end) 의 경과 중 면제 구간(merge 된 것)과 겹치지 않는 부분"""
    if end <= start:
        return 0
    total = end - start
    for s, e in exempt:
        overlap = min(end, e) - max(start, s)
        if overlap > 0:
            total -= overlap
    return total


def expiry_at(start: int, budget: int, exempt: Sequence[Interval]) -> int:
    """start 부터 흐르는 잔량 budget 이 0 이 되는 시각 — charged(start, T) == budget 인 가장 이른 T"""
    t, left = start, max(budget, 0)
    for s, e in exempt:
        if e <= t:
            continue
        if s > t:
            if left <= s - t:
                return t + left
            left -= s - t
        t = max(t, e)
    return t + left


@dataclass
class SeatClock:
    seat_no: int
    remaining_ms: int                      # 게임 시계 — 마지막 정산 시점
    conn_remaining_ms: int                 # 접속 시계 — 마지막 정산 시점
    disconnected_at_ms: Optional[int] = None
    grace: list[Interval] = field(default_factory=list)  # 서버 유예 창들
    frozen: bool = False                   # 탈락 또는 종료 — 두 시계가 더는 흐르지 않는다

    @property
    def connected(self) -> bool:
        return self.disconnected_at_ms is None

    def to_dict(self) -> dict:
        return {
            "seat_no": self.seat_no,
            "remaining_ms": self.remaining_ms,
            "conn_remaining_ms": self.conn_remaining_ms,
            "disconnected_at_ms": self.disconnected_at_ms,
            "grace": [list(i) for i in self.grace],
            "frozen": self.frozen,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "SeatClock":
        return cls(
            seat_no=data["seat_no"],
            remaining_ms=data["remaining_ms"],
            conn_remaining_ms=data["conn_remaining_ms"],
            disconnected_at_ms=data["disconnected_at_ms"],
            grace=[(s, e) for s, e in data["grace"]],
            frozen=data["frozen"],
        )


@dataclass(frozen=True)
class Expiry:
    seat_no: int
    reason: str      # TIME_FORFEIT | DISCONNECT_FORFEIT
    at_ms: int       # 소진 시각 — 같은 정산에서 여럿이면 이 순서로 탈락시킨다


@dataclass(frozen=True)
class Deadlines:
    """데드라인 ZSET 에 둘 것. 없는 항목은 지워야 한다"""
    clock_at: Optional[int]          # 현재 차례 좌석의 게임 시계 (게임당 하나)
    grace_at: dict[int, int]         # 끊긴 생존 좌석 → 접속 시계 소진 시각


@dataclass
class GameClocks:
    turn_started_at_ms: int
    seats: list[SeatClock]
    stopped_at_ms: Optional[int] = None
    started_at_ms: int = 0                 # 게임 시작 — 장기 장애 무효 대상 판정에 쓴다

    # ----- 생성·조회 -----

    @classmethod
    def start(cls, seat_nos: Iterable[int], now: int, *, initial_ms: int, budget_ms: int) -> "GameClocks":
        return cls(
            turn_started_at_ms=now,
            seats=[SeatClock(s, initial_ms, budget_ms) for s in sorted(seat_nos)],
            started_at_ms=now,
        )

    def seat(self, seat_no: int) -> SeatClock:
        for s in self.seats:
            if s.seat_no == seat_no:
                return s
        raise ValueError(f"Seat {seat_no} has no clock")

    @property
    def stopped(self) -> bool:
        return self.stopped_at_ms is not None

    def open_since(self) -> int:
        """아직 정산되지 않은 구간의 가장 이른 시작 — 이보다 먼저 끝난 장애 구간은 읽을 필요가 없다"""
        starts = [self.turn_started_at_ms]
        starts += [s.disconnected_at_ms for s in self.seats if not s.frozen and not s.connected]
        return min(starts)

    def exempt(self, seat_no: int, outages: Sequence[Interval]) -> list[Interval]:
        return merge([*self.seat(seat_no).grace, *outages])

    def game_remaining(self, seat_no: int, current_seat_no: Optional[int], now: int,
                       outages: Sequence[Interval] = ()) -> int:
        """seat_no 의 게임 시계 잔량 at now. 차례가 아니면 흐르지 않는다"""
        seat = self.seat(seat_no)
        if self.stopped or seat.frozen or seat_no != current_seat_no:
            return seat.remaining_ms
        return seat.remaining_ms - charged(self.turn_started_at_ms, now, self.exempt(seat_no, outages))

    def conn_remaining(self, seat_no: int, now: int, outages: Sequence[Interval] = ()) -> int:
        """seat_no 의 접속 시계 잔량 at now. 연결 중이면 흐르지 않는다"""
        seat = self.seat(seat_no)
        if self.stopped or seat.frozen or seat.connected:
            return seat.conn_remaining_ms
        return seat.conn_remaining_ms - charged(seat.disconnected_at_ms, now, self.exempt(seat_no, outages))

    def deadlines(self, current_seat_no: Optional[int], outages: Sequence[Interval] = ()) -> Deadlines:
        """지금 상태에서 각 시계가 0 이 되는 시각. 종료됐으면 전부 없음"""
        if self.stopped:
            return Deadlines(None, {})
        clock_at = None
        if current_seat_no is not None and not self.seat(current_seat_no).frozen:
            seat = self.seat(current_seat_no)
            clock_at = expiry_at(self.turn_started_at_ms, seat.remaining_ms,
                                 self.exempt(current_seat_no, outages))
        grace_at = {
            s.seat_no: expiry_at(s.disconnected_at_ms, s.conn_remaining_ms, self.exempt(s.seat_no, outages))
            for s in self.seats
            if not s.frozen and not s.connected
        }
        return Deadlines(clock_at, grace_at)

    def settle(self, current_seat_no: Optional[int], now: int,
               outages: Sequence[Interval] = ()) -> list[Expiry]:
        """now 시점에 소진된 좌석 — 소진 시각 순(동률은 seat_no). 상태를 바꾸지 않는다

        좌석마다 먼저 소진된 시계 하나만 낸다. 호출자가 이 순서로 탈락시킨다.
        """
        due = self.deadlines(current_seat_no, outages)
        found: dict[int, Expiry] = {}
        candidates = [(at, s, DISCONNECT_FORFEIT) for s, at in due.grace_at.items()]
        if due.clock_at is not None:
            candidates.append((due.clock_at, current_seat_no, TIME_FORFEIT))
        for at, seat_no, reason in sorted(candidates):
            if at <= now and seat_no not in found:
                found[seat_no] = Expiry(seat_no, reason, at)
        return sorted(found.values(), key=lambda e: (e.at_ms, e.seat_no))

    # ----- 사건 (전부 게임 락 안에서, now = 서버 시각) -----

    def close_turn(self, seat_no: int, now: int, outages: Sequence[Interval] = (),
                   *, increment_ms: int = 0) -> None:
        """seat_no 의 차례를 끝낸다 — 경과를 차감하고 증분을 더한다. 다음 차례는 begin_turn"""
        seat = self.seat(seat_no)
        seat.remaining_ms -= charged(self.turn_started_at_ms, now, self.exempt(seat_no, outages))
        seat.remaining_ms += increment_ms
        self.turn_started_at_ms = now
        self._prune(seat, current=False)

    def begin_turn(self, now: int) -> None:
        self.turn_started_at_ms = now

    def freeze(self, seat_no: int, now: int, outages: Sequence[Interval] = ()) -> None:
        """탈락 — 접속 시계를 정산하고 두 시계를 멈춘다. 게임 시계 정산은 호출자가 close_turn 으로"""
        seat = self.seat(seat_no)
        if seat.frozen:
            return
        if not seat.connected:
            seat.conn_remaining_ms -= charged(seat.disconnected_at_ms, now, self.exempt(seat_no, outages))
            seat.disconnected_at_ms = None
        seat.frozen = True
        seat.grace = []

    def stop(self, now: int, outages: Sequence[Interval] = ()) -> None:
        """게임 종료 — 남은 좌석을 정산하고 모든 시계를 멈춘다"""
        for seat in self.seats:
            self.freeze(seat.seat_no, now, outages)
        self.stopped_at_ms = now

    def disconnect(self, seat_no: int, now: int) -> bool:
        """끊김 기록. 이미 끊겼거나 탈락이면 아무것도 하지 않는다(시작 시각을 덮지 않는다)"""
        seat = self.seat(seat_no)
        if self.stopped or seat.frozen or not seat.connected:
            return False
        seat.disconnected_at_ms = now
        return True

    def reconnect(self, seat_no: int, current_seat_no: Optional[int], now: int,
                  outages: Sequence[Interval] = ()) -> bool:
        """재접속 — 끊긴 구간을 접속 시계에서 차감한다(리셋 없음). 서버 유예 창은 now 에서 끝난다"""
        seat = self.seat(seat_no)
        if self.stopped or seat.frozen or seat.connected:
            return False
        seat.conn_remaining_ms -= charged(seat.disconnected_at_ms, now, self.exempt(seat_no, outages))
        seat.disconnected_at_ms = None
        seat.grace = [(s, min(e, now)) for s, e in seat.grace if s < now]
        self._prune(seat, current=seat_no == current_seat_no)
        return True

    def apply_grace(self, seat_no: int, disconnected_at_ms: int, max_ms: int) -> bool:
        """서버 유예(배포) — 그 좌석이 아직 같은 끊김 상태일 때만 [끊김, 끊김 + max) 를 면제한다"""
        seat = self.seat(seat_no)
        if self.stopped or seat.frozen or seat.disconnected_at_ms != disconnected_at_ms:
            return False
        window = (disconnected_at_ms, disconnected_at_ms + max_ms)
        if window in seat.grace:
            return False
        seat.grace = merge([*seat.grace, window])
        return True

    def _prune(self, seat: SeatClock, *, current: bool) -> None:
        """아직 정산되지 않은 구간에 걸리지 않는 유예 창은 버린다"""
        open_starts = []
        if current:
            open_starts.append(self.turn_started_at_ms)
        if not seat.connected:
            open_starts.append(seat.disconnected_at_ms)
        if not open_starts:
            seat.grace = []
            return
        oldest = min(open_starts)
        seat.grace = [(s, e) for s, e in seat.grace if e > oldest]

    # ----- 공개 -----

    def public_view(self, current_seat_no: Optional[int], now: int,
                    outages: Sequence[Interval] = ()) -> dict:
        """전원에게 공개하는 잔량 (§8 — 숨길 이유가 없다). 필드 이름은 잠정(§12 확정은 7단계)"""
        due = self.deadlines(current_seat_no, outages)
        return {
            "seats": [
                {
                    "seat_no": s.seat_no,
                    "remaining_ms": max(0, self.game_remaining(s.seat_no, current_seat_no, now, outages)),
                    "connection_remaining_ms": max(0, self.conn_remaining(s.seat_no, now, outages)),
                    "connected": s.connected,
                }
                for s in self.seats
            ],
            "current_expires_at_ms": due.clock_at,
        }

    # ----- 직렬화 -----

    def to_dict(self) -> dict:
        return {
            "v": CLOCKS_SCHEMA_VERSION,
            "turn_started_at_ms": self.turn_started_at_ms,
            "stopped_at_ms": self.stopped_at_ms,
            "started_at_ms": self.started_at_ms,
            "seats": [s.to_dict() for s in self.seats],
        }

    @classmethod
    def from_dict(cls, data: dict) -> "GameClocks":
        if data.get("v") != CLOCKS_SCHEMA_VERSION:
            raise ValueError(f"clocks schema {data.get('v')} != {CLOCKS_SCHEMA_VERSION}")
        return cls(
            turn_started_at_ms=data["turn_started_at_ms"],
            seats=[SeatClock.from_dict(s) for s in data["seats"]],
            stopped_at_ms=data["stopped_at_ms"],
            started_at_ms=data["started_at_ms"],
        )
