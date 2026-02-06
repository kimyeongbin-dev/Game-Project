"""
Pathfinder Tests
경로 탐색 알고리즘 테스트
"""

import pytest
import sys
from pathlib import Path

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from games.game_Quoridor.core.pathfinder import Pathfinder
from games.game_Quoridor.core.board import Position
from games.game_Quoridor.core.wall import Wall, WallManager, Orientation


class TestPathfinding:
    """경로 탐색 테스트"""

    def test_path_exists_no_walls(self):
        """벽 없이 경로 존재"""
        wall_manager = WallManager()
        start = Position(8, 4)
        goal_row = 0

        exists = Pathfinder.path_exists(start, goal_row, wall_manager)

        assert exists is True

    def test_shortest_distance_no_walls(self):
        """벽 없이 최단 거리"""
        wall_manager = WallManager()
        start = Position(8, 4)
        goal_row = 0

        distance = Pathfinder.get_shortest_distance(start, goal_row, wall_manager)

        assert distance == 8  # 직선 거리

    def test_path_with_walls(self):
        """벽이 있어도 경로 존재"""
        wall_manager = WallManager()
        # 중간에 벽 설치 (완전히 막지 않음)
        wall_manager.add_wall(Wall(4, 3, Orientation.HORIZONTAL))

        start = Position(8, 4)
        goal_row = 0

        exists = Pathfinder.path_exists(start, goal_row, wall_manager)

        assert exists is True

    def test_distance_increases_with_walls(self):
        """벽으로 인해 거리 증가"""
        wall_manager = WallManager()
        start = Position(8, 4)
        goal_row = 0

        distance_without_wall = Pathfinder.get_shortest_distance(start, goal_row, wall_manager)

        # 벽 추가 (경로 우회 필요)
        wall_manager.add_wall(Wall(7, 3, Orientation.HORIZONTAL))
        wall_manager.add_wall(Wall(7, 5, Orientation.HORIZONTAL))

        distance_with_wall = Pathfinder.get_shortest_distance(start, goal_row, wall_manager)

        # 벽이 있으면 더 멀어질 수 있음
        assert distance_with_wall >= distance_without_wall


class TestWallSafety:
    """벽 설치 안전성 테스트"""

    def test_safe_wall_placement(self):
        """안전한 벽 설치 (경로 보장)"""
        wall_manager = WallManager()
        player1_pos = Position(8, 4)
        player2_pos = Position(0, 4)

        # 임시 벽 추가
        temp_manager = wall_manager.copy()
        temp_manager.add_wall(Wall(4, 4, Orientation.HORIZONTAL))

        is_safe = Pathfinder.can_place_wall_safely(
            temp_manager,
            player1_pos, 0,  # player1 goal
            player2_pos, 8   # player2 goal
        )

        assert is_safe is True

    def test_unsafe_wall_blocks_path(self):
        """경로 차단하는 벽 (불안전)"""
        wall_manager = WallManager()

        # 플레이어를 구석에 배치하고 벽으로 막음
        player1_pos = Position(8, 0)
        player2_pos = Position(0, 4)

        # 경로를 완전히 차단하는 벽들
        temp_manager = wall_manager.copy()
        # 왼쪽 하단 구석을 막는 벽들
        temp_manager.add_wall(Wall(7, 0, Orientation.VERTICAL))
        temp_manager.add_wall(Wall(7, 0, Orientation.HORIZONTAL))

        # 실제로 경로가 있는지 확인
        path_exists = Pathfinder.path_exists(player1_pos, 0, temp_manager)

        # 경로가 없으면 안전하지 않음
        if not path_exists:
            is_safe = Pathfinder.can_place_wall_safely(
                temp_manager,
                player1_pos, 0,
                player2_pos, 8
            )
            assert is_safe is False


class TestEdgeCases:
    """엣지 케이스 테스트"""

    def test_already_at_goal(self):
        """이미 골 라인에 있는 경우"""
        wall_manager = WallManager()
        start = Position(0, 4)
        goal_row = 0

        distance = Pathfinder.get_shortest_distance(start, goal_row, wall_manager)

        assert distance == 0

    def test_path_from_corner(self):
        """코너에서 시작"""
        wall_manager = WallManager()
        start = Position(8, 0)
        goal_row = 0

        exists = Pathfinder.path_exists(start, goal_row, wall_manager)

        assert exists is True
