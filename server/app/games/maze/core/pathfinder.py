"""
Pathfinder Module
BFS를 이용한 경로 검증

말은 경로를 막지 않는다 (maze.md §5 — 통과·중첩 허용). 그래서 벽만 본다.
"""

from collections import deque
from typing import Iterable, Optional, Sequence, Set

from .board import Board, Goal, Position, reaches_any
from .player import Player
from .wall import WallManager


class Pathfinder:
    """BFS 기반 경로 탐색기"""

    @staticmethod
    def find_shortest_path(
        start: Position,
        goals: Sequence[Goal],
        wall_manager: WallManager
    ) -> Optional[list[Position]]:
        """
        시작 위치에서 goals 중 어느 하나까지의 최단 경로 찾기

        Returns:
            경로 리스트 (시작 위치 포함) 또는 None (경로 없음)
        """
        if reaches_any(start, goals):
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

                if reaches_any(new_pos, goals):
                    return new_path

                visited.add(new_pos.to_tuple())
                queue.append((new_pos, new_path))

        return None

    @staticmethod
    def has_path_to_goal(
        start: Position,
        goals: Sequence[Goal],
        wall_manager: WallManager
    ) -> bool:
        """목표까지 경로가 존재하는지 확인"""
        return Pathfinder.find_shortest_path(start, goals, wall_manager) is not None

    @staticmethod
    def get_shortest_distance(
        start: Position,
        goals: Sequence[Goal],
        wall_manager: WallManager
    ) -> int:
        """목표까지의 최단 거리 반환 (경로 없으면 -1)"""
        path = Pathfinder.find_shortest_path(start, goals, wall_manager)
        if path is None:
            return -1
        return len(path) - 1  # 시작 위치 제외

    @staticmethod
    def can_place_wall_safely(
        wall_manager: WallManager,
        seats: Iterable[Player]
    ) -> bool:
        """
        현재 벽 상태에서 주어진 좌석 전원이 목표에 도달 가능한지 확인

        탈락자를 걸러내는 것은 호출자의 몫이다 — 탈락자를 넣으면 그 말이 갇힌
        순간부터 모든 벽 설치가 영구히 거절된다 (maze.md §7·§9).
        """
        return all(
            Pathfinder.has_path_to_goal(seat.position, seat.goals, wall_manager)
            for seat in seats
        )
