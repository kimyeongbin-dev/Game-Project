"""
Game State Module
게임 상태 관리 (핵심 모듈)

좌석 수는 배치 테이블(layouts.py)이 정한다. 이 모듈은 인원을 가정하지 않는다.
to_dict() 결과가 Redis `game:<id>:state` 의 값 전체다 (maze.md §8) — 규칙 상태만
담고, 시계·시야·유저 식별자는 별도 키의 몫이다.
"""

import random
import uuid
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Optional

from app.core.time import utcnow

from .board import Board, Position
from .layouts import get_layout
from .player import Player
from .wall import Wall, WallManager, Orientation
from .move_validator import MoveValidator, Rejection
from .pathfinder import Pathfinder


# to_dict() 형태가 바뀌면 올린다. 이어받기 배포 중 구·신 워커가 같은 키를 읽는다
SCHEMA_VERSION = 1

# 턴당 허용 거절 횟수 (maze.md §7). 이를 넘긴 거절에서 그 턴의 벽 설치가 잠긴다
PROBE_LIMIT = 2

# 거절 카운터에 넣는 사유 — 숨은 벽의 존재를 드러내는 거절들.
# 좌표 범위 밖·방향값 무효는 정보가 없으므로 세지 않는다
_PROBE_REJECTIONS = (Rejection.INVALID_WALL_POSITION, Rejection.WALL_BLOCKS_PATH)


class GameStatus(Enum):
    """게임 상태"""
    IN_PROGRESS = "in_progress"
    FINISHED = "finished"


class EndReason(Enum):
    """게임 종료 사유 (maze.md §9). server_fault 는 상태를 잃었을 때라 여기 없다"""
    GOAL_REACHED = "goal_reached"
    LAST_STANDING = "last_standing"


class ActionType(Enum):
    """액션 타입"""
    MOVE = "move"
    WALL = "wall"


@dataclass
class Action:
    """게임 액션"""
    action_type: ActionType
    row: int
    col: int
    orientation: Optional[Orientation] = None

    def to_dict(self) -> dict:
        result = {
            "type": self.action_type.value,
            "row": self.row,
            "col": self.col
        }
        if self.orientation:
            result["orientation"] = self.orientation.value
        return result


class GameState:
    """미로 대결 게임 상태"""

    def __init__(
        self,
        mode: str = "duel",
        *,
        game_id: Optional[str] = None,
        rng: Optional[random.Random] = None
    ):
        layout = get_layout(mode)

        self.game_id = game_id or str(uuid.uuid4())
        self.mode = mode
        self.status = GameStatus.IN_PROGRESS
        self.end_reason: Optional[EndReason] = None
        self.winner_seat_no: Optional[int] = None
        self.current_seat_no = 1
        self.turn_count = 0
        self.wall_rejections = 0

        self.seats: list[Player] = [
            Player.from_slot(i + 1, slot, layout.walls_per_seat)
            for i, slot in enumerate(layout.assign(rng))
        ]

        self.wall_manager = WallManager()

        self.created_at = utcnow()
        self.updated_at = self.created_at

    # ----- 조회 -----

    def seat(self, seat_no: int) -> Player:
        """좌석 조회. 없는 좌석이면 ValueError"""
        if not (1 <= seat_no <= len(self.seats)):
            raise ValueError(f"Invalid seat_no: {seat_no}")
        return self.seats[seat_no - 1]

    @property
    def current_player(self) -> Player:
        """현재 차례 좌석"""
        return self.seat(self.current_seat_no)

    @property
    def survivors(self) -> list[Player]:
        """탈락하지 않은 좌석 (seat_no 오름차순)"""
        return [p for p in self.seats if not p.is_eliminated]

    @property
    def is_finished(self) -> bool:
        return self.status == GameStatus.FINISHED

    @property
    def walls_locked(self) -> bool:
        """이번 턴 벽 설치가 잠겼는가 (maze.md §7)"""
        return self.wall_rejections > PROBE_LIMIT

    def get_valid_pawn_moves(self) -> list[Position]:
        """현재 좌석의 유효한 말 이동 목록"""
        return MoveValidator.get_valid_pawn_moves(self.current_player, self.wall_manager)

    def get_valid_wall_placements(self) -> list[Wall]:
        """현재 좌석의 유효한 벽 설치 목록 (서버 AI 전용 — 전체 벽을 본다)"""
        if self.walls_locked:
            return []
        return MoveValidator.get_valid_wall_placements(
            self.current_player, self.survivors, self.wall_manager
        )

    def get_player_distance_to_goal(self, seat_no: int) -> int:
        """좌석의 목표까지 최단 거리 (경로 없으면 -1)"""
        player = self.seat(seat_no)
        return Pathfinder.get_shortest_distance(player.position, player.goals, self.wall_manager)

    # ----- 행동 -----

    def move(self, seat_no: int, row: int, col: int) -> Optional[Rejection]:
        """말 이동 (maze.md §5 검증 순서). 성공 시 None"""
        rejection = self._check_actor(seat_no)
        if rejection:
            return rejection

        if not Board.is_valid_cell(row, col):
            return Rejection.INVALID_MOVE
        target = Position(row, col)

        player = self.current_player
        if not MoveValidator.is_valid_pawn_move(player, target, self.wall_manager):
            return Rejection.INVALID_MOVE

        player.move_to(target)
        self._complete_action(player)

        if player.has_reached_goal():
            self._finish(EndReason.GOAL_REACHED, seat_no)
        else:
            self._advance_turn()
        return None

    def place_wall(self, seat_no: int, row: int, col: int, orientation) -> Optional[Rejection]:
        """
        벽 설치 (maze.md §7 검증 순서). 성공 시 None

        숨은 벽을 드러내는 거절(겹침·교차, 경로 차단)은 같은 카운터로 센다.
        PROBE_LIMIT 를 넘긴 거절은 원래 코드를 반환하며 그 턴의 벽 설치를 잠근다.
        """
        rejection = self._check_actor(seat_no)
        if rejection:
            return rejection

        player = self.current_player
        if not player.has_walls():
            return Rejection.NO_WALLS_REMAINING
        if self.walls_locked:
            return Rejection.PROBE_LIMIT_EXCEEDED

        try:
            wall = Wall(row, col, Orientation(orientation))
        except ValueError:
            return Rejection.INVALID_WALL_POSITION  # 범위 밖 — 세지 않는다

        rejection = MoveValidator.check_wall_placement(
            wall, player, self.survivors, self.wall_manager
        )
        if rejection:
            if rejection in _PROBE_REJECTIONS:
                self.wall_rejections += 1
            return rejection

        self.wall_manager.add_wall(wall)
        player.use_wall()
        self._complete_action(player)
        self._advance_turn()
        return None

    def eliminate(self, seat_no: int, reason: str) -> Optional[Rejection]:
        """
        좌석 탈락 (maze.md §9). 성공 시 None

        생존자가 1명 남으면 last_standing 으로 종료한다. 현재 차례 좌석이 탈락하면
        즉시 다음 생존자로 넘긴다.
        """
        if self.is_finished:
            return Rejection.GAME_ALREADY_ENDED

        player = self.seat(seat_no)
        if player.is_eliminated:
            raise ValueError(f"Seat {seat_no} is already eliminated")

        order = len(self.seats) - len(self.survivors) + 1
        player.eliminate(order, reason)
        self.updated_at = utcnow()

        survivors = self.survivors
        if len(survivors) == 1:
            self._finish(EndReason.LAST_STANDING, survivors[0].seat_no)
        elif seat_no == self.current_seat_no:
            self._advance_turn()
        return None

    # ----- 결과 -----

    def standings(self) -> list[dict]:
        """
        순위 (maze.md §9). [{"seat_no", "rank"}] — rank 오름차순

        도달자 > 생존자(남은 거리 짧은 순 → 사용한 턴 적은 순) > 탈락자(나중에
        탈락한 쪽이 상위). 동률은 공동 순위이며 다음 순위를 건너뛴다 (1,2,2,4).
        """
        def key(p: Player) -> tuple:
            if self.end_reason == EndReason.GOAL_REACHED and p.seat_no == self.winner_seat_no:
                return (0, 0, 0)
            if p.is_eliminated:
                return (2, -p.eliminated_order, 0)
            distance = self.get_player_distance_to_goal(p.seat_no)
            return (1, distance if distance >= 0 else Board.SIZE ** 2, p.turns_taken)

        keys = {p.seat_no: key(p) for p in self.seats}
        ranked = [
            {"seat_no": seat_no, "rank": 1 + sum(1 for k in keys.values() if k < own)}
            for seat_no, own in keys.items()
        ]
        return sorted(ranked, key=lambda r: (r["rank"], r["seat_no"]))

    # ----- 내부 -----

    def _check_actor(self, seat_no: int) -> Optional[Rejection]:
        if self.is_finished:
            return Rejection.GAME_ALREADY_ENDED
        if seat_no != self.current_seat_no:
            return Rejection.NOT_YOUR_TURN
        return None

    def _complete_action(self, player: Player) -> None:
        player.turns_taken += 1
        self.turn_count += 1
        self.updated_at = utcnow()

    def _advance_turn(self) -> None:
        """seat_no 오름차순 순환, 탈락자 건너뜀 (maze.md §11). 거절 카운터 리셋"""
        n = len(self.seats)
        for step in range(1, n + 1):
            candidate = self.seats[(self.current_seat_no - 1 + step) % n]
            if not candidate.is_eliminated:
                self.current_seat_no = candidate.seat_no
                break
        self.wall_rejections = 0

    def _finish(self, reason: EndReason, winner_seat_no: int) -> None:
        self.status = GameStatus.FINISHED
        self.end_reason = reason
        self.winner_seat_no = winner_seat_no

    # ----- 복사·직렬화 -----

    def copy(self) -> "GameState":
        """게임 상태 깊은 복사"""
        return GameState.from_dict(self.to_dict())

    def to_dict(self) -> dict:
        """Redis `game:<id>:state` 에 그대로 저장되는 형태"""
        return {
            "schema_version": SCHEMA_VERSION,
            "game_id": self.game_id,
            "mode": self.mode,
            "status": self.status.value,
            "end_reason": self.end_reason.value if self.end_reason else None,
            "winner_seat_no": self.winner_seat_no,
            "current_seat_no": self.current_seat_no,
            "turn_count": self.turn_count,
            "wall_rejections": self.wall_rejections,
            "seats": [p.to_dict() for p in self.seats],
            "walls": [wall.to_dict() for wall in self.wall_manager.walls],
            "created_at": self.created_at.isoformat() + "Z",
            "updated_at": self.updated_at.isoformat() + "Z",
        }

    @classmethod
    def from_dict(cls, data: dict) -> "GameState":
        """
        to_dict() 결과에서 복원. schema_version 이 다르면 ValueError

        배치 테이블을 다시 읽지 않는다 — 좌석별 goals·walls_remaining 이 저장돼
        있으므로 테이블이 바뀌어도 진행 중 게임은 그대로 이어진다.
        """
        version = data.get("schema_version")
        if version != SCHEMA_VERSION:
            raise ValueError(f"Unsupported schema_version: {version}")

        game = cls.__new__(cls)
        game.game_id = data["game_id"]
        game.mode = data["mode"]
        game.status = GameStatus(data["status"])
        game.end_reason = EndReason(data["end_reason"]) if data["end_reason"] else None
        game.winner_seat_no = data["winner_seat_no"]
        game.current_seat_no = data["current_seat_no"]
        game.turn_count = data["turn_count"]
        game.wall_rejections = data["wall_rejections"]

        game.seats = sorted(
            (Player.from_dict(p) for p in data["seats"]), key=lambda p: p.seat_no
        )

        game.wall_manager = WallManager()
        for wall_data in data["walls"]:
            game.wall_manager.add_wall(Wall.from_dict(wall_data))

        game.created_at = datetime.fromisoformat(data["created_at"].rstrip("Z"))
        game.updated_at = datetime.fromisoformat(data["updated_at"].rstrip("Z"))

        return game
