"""
Pathfinder Module
BFS를 이용한 경로 검증
"""

from collections import deque
from typing import Optional, Set

from .board import Board, Position
from .wall import WallManager


class Pathfinder:
    """BFS 기반 경로 탐색기"""

    @staticmethod
    def find_shortest_path(
        start: Position,
        goal_row: int,
        wall_manager: WallManager,
        other_player_pos: Optional[Position] = None
    ) -> Optional[list[Position]]:
        """
        시작 위치에서 목표 행까지의 최단 경로 찾기

        Args:
            start: 시작 위치
            goal_row: 목표 행 (0 또는 8)
            wall_manager: 벽 관리자
            other_player_pos: 상대 플레이어 위치 (점프 계산 무시, 단순 경로용)

        Returns:
            경로 리스트 (시작 위치 포함) 또는 None (경로 없음)
        """
        if start.row == goal_row:
            return [start]

        visited: Set[tuple] = {start.to_tuple()}
        queue = deque([(start, [start])])

        while queue:
            current, path = queue.popleft()

            for dr, dc in Board.DIRECTIONS:
                new_row, new_col = current.row + dr, current.col + dc

                if not Board.is_valid_cell(new_row, new_col):
                    continue

                new_pos = Position(new_row, new_col)

                if new_pos.to_tuple() in visited:
                    continue

                if wall_manager.is_move_blocked(current, new_pos):
                    continue

                new_path = path + [new_pos]

                if new_row == goal_row:
                    return new_path

                visited.add(new_pos.to_tuple())
                queue.append((new_pos, new_path))

        return None

    @staticmethod
    def has_path_to_goal(
        start: Position,
        goal_row: int,
        wall_manager: WallManager
    ) -> bool:
        """목표까지 경로가 존재하는지 확인"""
        return Pathfinder.find_shortest_path(start, goal_row, wall_manager) is not None

    @staticmethod
    def get_shortest_distance(
        start: Position,
        goal_row: int,
        wall_manager: WallManager
    ) -> int:
        """목표까지의 최단 거리 반환 (경로 없으면 -1)"""
        path = Pathfinder.find_shortest_path(start, goal_row, wall_manager)
        if path is None:
            return -1
        return len(path) - 1  # 시작 위치 제외

    @staticmethod
    def can_place_wall_safely(
        wall_manager: WallManager,
        player1_pos: Position,
        player1_goal: int,
        player2_pos: Position,
        player2_goal: int
    ) -> bool:
        """
        현재 벽 상태에서 양 플레이어 모두 목표에 도달 가능한지 확인

        Args:
            wall_manager: 현재 벽 상태
            player1_pos: 플레이어 1 위치
            player1_goal: 플레이어 1 목표 행
            player2_pos: 플레이어 2 위치
            player2_goal: 플레이어 2 목표 행

        Returns:
            양쪽 모두 경로가 있으면 True
        """
        p1_has_path = Pathfinder.has_path_to_goal(player1_pos, player1_goal, wall_manager)
        if not p1_has_path:
            return False

        p2_has_path = Pathfinder.has_path_to_goal(player2_pos, player2_goal, wall_manager)
        return p2_has_path
