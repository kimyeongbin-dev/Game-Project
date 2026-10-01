"""
Move Validator Module
이동 및 벽 설치 유효성 검사

이동은 직교 인접 1칸 + 사이 변에 벽 없음, 이것뿐이다. 다른 말의 위치는 관여하지
않는다 — 점프 규칙을 두지 않고 말 중첩을 허용한다 (maze.md §5).
"""

from enum import Enum
from typing import Optional, Sequence

from .board import Board, Position
from .player import Player
from .wall import Wall, WallManager, Orientation
from .pathfinder import Pathfinder


class Rejection(str, Enum):
    """행동 거절 사유. 값이 곧 maze.md §13 에러 코드다"""
    GAME_ALREADY_ENDED = "game_already_ended"
    NOT_YOUR_TURN = "not_your_turn"
    INVALID_MOVE = "invalid_move"
    INVALID_WALL_POSITION = "invalid_wall_position"
    NO_WALLS_REMAINING = "no_walls_remaining"
    WALL_BLOCKS_PATH = "wall_blocks_path"
    PROBE_LIMIT_EXCEEDED = "probe_limit_exceeded"


class MoveValidator:
    """이동 및 벽 설치 유효성 검사기"""

    @staticmethod
    def get_valid_pawn_moves(
        player: Player,
        wall_manager: WallManager
    ) -> list[Position]:
        """플레이어가 이동할 수 있는 모든 유효한 위치 반환"""
        current_pos = player.position
        return [
            new_pos
            for new_pos in Board.get_adjacent_positions(current_pos)
            if not wall_manager.is_move_blocked(current_pos, new_pos)
        ]

    @staticmethod
    def is_valid_pawn_move(
        player: Player,
        target: Position,
        wall_manager: WallManager
    ) -> bool:
        """특정 위치로의 이동이 유효한지 확인"""
        return target in MoveValidator.get_valid_pawn_moves(player, wall_manager)

    @staticmethod
    def check_wall_placement(
        wall: Wall,
        player: Player,
        survivors: Sequence[Player],
        wall_manager: WallManager
    ) -> Optional[Rejection]:
        """
        벽 설치 검증 (maze.md §7 순서). 통과하면 None

        Args:
            wall: 설치할 벽 (좌표 범위는 Wall 생성 시 이미 검증됨)
            player: 벽을 설치할 좌석
            survivors: 경로 보장 검증 대상 — **생존 좌석만**
            wall_manager: 벽 관리자
        """
        if not player.has_walls():
            return Rejection.NO_WALLS_REMAINING

        # 기존 벽과 겹침·교차
        if not wall_manager.can_place_wall(wall):
            return Rejection.INVALID_WALL_POSITION

        # 경로 보장 (임시로 벽 설치 후 검사)
        temp_manager = wall_manager.copy()
        temp_manager.add_wall(wall)
        if not Pathfinder.can_place_wall_safely(temp_manager, survivors):
            return Rejection.WALL_BLOCKS_PATH

        return None

    @staticmethod
    def is_valid_wall_placement(
        wall: Wall,
        player: Player,
        survivors: Sequence[Player],
        wall_manager: WallManager
    ) -> bool:
        """벽 설치가 유효한지 확인"""
        return MoveValidator.check_wall_placement(wall, player, survivors, wall_manager) is None

    @staticmethod
    def get_valid_wall_placements(
        player: Player,
        survivors: Sequence[Player],
        wall_manager: WallManager
    ) -> list[Wall]:
        """
        설치 가능한 모든 벽 위치 반환

        전체 벽을 보고 계산하므로 Fog of War 를 무시한다 — 서버 AI 전용이며
        클라이언트에 내보내지 않는다 (maze.md §7).
        """
        if not player.has_walls():
            return []

        valid_walls = []

        for row in range(Board.WALL_POSITIONS):
            for col in range(Board.WALL_POSITIONS):
                for orientation in Orientation:
                    wall = Wall(row, col, orientation)

                    if MoveValidator.is_valid_wall_placement(
                        wall, player, survivors, wall_manager
                    ):
                        valid_walls.append(wall)

        return valid_walls
