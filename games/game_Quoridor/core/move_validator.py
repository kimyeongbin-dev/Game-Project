"""
Move Validator Module
이동 및 벽 설치 유효성 검사
"""

from typing import Optional

from .board import Board, Position
from .player import Player
from .wall import Wall, WallManager, Orientation
from .pathfinder import Pathfinder


class MoveValidator:
    """이동 및 벽 설치 유효성 검사기"""

    @staticmethod
    def get_valid_pawn_moves(
        player: Player,
        opponent: Player,
        wall_manager: WallManager
    ) -> list[Position]:
        """
        플레이어가 이동할 수 있는 모든 유효한 위치 반환

        Args:
            player: 이동할 플레이어
            opponent: 상대 플레이어
            wall_manager: 벽 관리자

        Returns:
            유효한 이동 위치 리스트
        """
        valid_moves = []
        current_pos = player.position
        opponent_pos = opponent.position

        for dr, dc in Board.DIRECTIONS:
            new_row, new_col = current_pos.row + dr, current_pos.col + dc

            if not Board.is_valid_cell(new_row, new_col):
                continue

            new_pos = Position(new_row, new_col)

            # 벽에 막혀있는지 확인
            if wall_manager.is_move_blocked(current_pos, new_pos):
                continue

            # 상대방 위치인지 확인
            if new_pos == opponent_pos:
                # 점프 로직
                jump_moves = MoveValidator._get_jump_moves(
                    current_pos, opponent_pos, dr, dc, wall_manager
                )
                valid_moves.extend(jump_moves)
            else:
                valid_moves.append(new_pos)

        return valid_moves

    @staticmethod
    def _get_jump_moves(
        current_pos: Position,
        opponent_pos: Position,
        dr: int,
        dc: int,
        wall_manager: WallManager
    ) -> list[Position]:
        """
        상대방을 점프할 때의 유효한 이동 위치 계산

        Args:
            current_pos: 현재 위치
            opponent_pos: 상대방 위치
            dr, dc: 이동 방향
            wall_manager: 벽 관리자

        Returns:
            점프 가능한 위치 리스트
        """
        jump_moves = []

        # 직선 점프 시도 (상대 뒤로)
        jump_row, jump_col = opponent_pos.row + dr, opponent_pos.col + dc

        if Board.is_valid_cell(jump_row, jump_col):
            jump_pos = Position(jump_row, jump_col)
            if not wall_manager.is_move_blocked(opponent_pos, jump_pos):
                # 직선 점프 가능
                jump_moves.append(jump_pos)
                return jump_moves

        # 직선 점프 불가 -> 대각선 점프
        # 좌우 또는 상하로 대각선 이동
        if dr != 0:  # 상하 이동 중이면 좌우로 대각선
            diagonals = [(0, -1), (0, 1)]
        else:  # 좌우 이동 중이면 상하로 대각선
            diagonals = [(-1, 0), (1, 0)]

        for ddr, ddc in diagonals:
            diag_row, diag_col = opponent_pos.row + ddr, opponent_pos.col + ddc
            if Board.is_valid_cell(diag_row, diag_col):
                diag_pos = Position(diag_row, diag_col)
                if not wall_manager.is_move_blocked(opponent_pos, diag_pos):
                    jump_moves.append(diag_pos)

        return jump_moves

    @staticmethod
    def is_valid_pawn_move(
        player: Player,
        opponent: Player,
        target: Position,
        wall_manager: WallManager
    ) -> bool:
        """
        특정 위치로의 이동이 유효한지 확인

        Args:
            player: 이동할 플레이어
            opponent: 상대 플레이어
            target: 목표 위치
            wall_manager: 벽 관리자

        Returns:
            유효하면 True
        """
        valid_moves = MoveValidator.get_valid_pawn_moves(player, opponent, wall_manager)
        return target in valid_moves

    @staticmethod
    def get_valid_wall_placements(
        player: Player,
        opponent: Player,
        wall_manager: WallManager
    ) -> list[Wall]:
        """
        플레이어가 설치할 수 있는 모든 유효한 벽 위치 반환

        Args:
            player: 벽을 설치할 플레이어
            opponent: 상대 플레이어
            wall_manager: 벽 관리자

        Returns:
            유효한 벽 리스트
        """
        if not player.has_walls():
            return []

        valid_walls = []

        for row in range(Board.WALL_POSITIONS):
            for col in range(Board.WALL_POSITIONS):
                for orientation in Orientation:
                    wall = Wall(row, col, orientation)

                    if MoveValidator.is_valid_wall_placement(
                        wall, player, opponent, wall_manager
                    ):
                        valid_walls.append(wall)

        return valid_walls

    @staticmethod
    def is_valid_wall_placement(
        wall: Wall,
        player: Player,
        opponent: Player,
        wall_manager: WallManager
    ) -> bool:
        """
        벽 설치가 유효한지 확인

        Args:
            wall: 설치할 벽
            player: 벽을 설치할 플레이어
            opponent: 상대 플레이어
            wall_manager: 벽 관리자

        Returns:
            유효하면 True
        """
        # 1. 남은 벽 확인
        if not player.has_walls():
            return False

        # 2. 다른 벽과 충돌 확인
        if not wall_manager.can_place_wall(wall):
            return False

        # 3. 경로 보장 확인 (임시로 벽 설치 후 검사)
        temp_manager = wall_manager.copy()
        temp_manager.add_wall(wall)

        return Pathfinder.can_place_wall_safely(
            temp_manager,
            player.position,
            player.goal_row,
            opponent.position,
            opponent.goal_row
        )
