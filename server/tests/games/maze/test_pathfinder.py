"""
Pathfinder Tests
경로 탐색 알고리즘 테스트
"""

import pytest


from app.games.maze.core.pathfinder import Pathfinder
from app.games.maze.core.board import Position, Goal
from app.games.maze.core.player import Player
from app.games.maze.core.wall import Wall, WallManager, Orientation


class TestPathfinding:
    """경로 탐색 테스트"""

    def test_path_exists_no_walls(self):
        """벽 없이 경로 존재"""
        wall_manager = WallManager()
        start = Position(8, 4)
        goals = [Goal("row", 0)]

        exists = Pathfinder.has_path_to_goal(start, goals, wall_manager)

        assert exists is True

    def test_shortest_distance_no_walls(self):
        """벽 없이 최단 거리"""
        wall_manager = WallManager()
        start = Position(8, 4)
        goals = [Goal("row", 0)]

        distance = Pathfinder.get_shortest_distance(start, goals, wall_manager)

        assert distance == 8  # 직선 거리

    def test_path_with_walls(self):
        """벽이 있어도 경로 존재"""
        wall_manager = WallManager()
        # 중간에 벽 설치 (완전히 막지 않음)
        wall_manager.add_wall(Wall(4, 3, Orientation.HORIZONTAL))

        start = Position(8, 4)
        goals = [Goal("row", 0)]

        exists = Pathfinder.has_path_to_goal(start, goals, wall_manager)

        assert exists is True

    def test_distance_increases_with_walls(self):
        """벽으로 인해 거리 증가"""
        wall_manager = WallManager()
        start = Position(8, 4)
        goals = [Goal("row", 0)]

        distance_without_wall = Pathfinder.get_shortest_distance(start, goals, wall_manager)

        # 벽 추가 (경로 우회 필요)
        wall_manager.add_wall(Wall(7, 3, Orientation.HORIZONTAL))
        wall_manager.add_wall(Wall(7, 5, Orientation.HORIZONTAL))

        distance_with_wall = Pathfinder.get_shortest_distance(start, goals, wall_manager)

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

        seat1 = Player(seat_no=1, position=player1_pos, goals=(Goal("row", 0),), walls_remaining=10)
        seat2 = Player(seat_no=2, position=player2_pos, goals=(Goal("row", 8),), walls_remaining=10)

        is_safe = Pathfinder.can_place_wall_safely(temp_manager, [seat1, seat2])

        assert is_safe is True

    def test_unsafe_wall_blocks_path(self):
        """경로 차단하는 벽 (불안전)"""
        wall_manager = WallManager()

        # 플레이어를 구석에 배치하고 벽으로 막음
        player1_pos = Position(8, 0)
        player2_pos = Position(0, 4)

        # 왼쪽 하단 구석 (8,0)-(7,0) 두 칸을 가두는 벽들
        temp_manager = wall_manager.copy()
        assert temp_manager.add_wall(Wall(7, 0, Orientation.VERTICAL)) is True    # (7,0)|(7,1), (8,0)|(8,1)
        assert temp_manager.add_wall(Wall(6, 0, Orientation.HORIZONTAL)) is True  # (6,0)/(7,0), (6,1)/(7,1)

        assert Pathfinder.has_path_to_goal(player1_pos, [Goal("row", 0)], temp_manager) is False

        seat1 = Player(seat_no=1, position=player1_pos, goals=(Goal("row", 0),), walls_remaining=10)
        seat2 = Player(seat_no=2, position=player2_pos, goals=(Goal("row", 8),), walls_remaining=10)
        assert Pathfinder.can_place_wall_safely(temp_manager, [seat1, seat2]) is False
        # 갇힌 좌석을 빼면 (탈락자) 안전하다
        assert Pathfinder.can_place_wall_safely(temp_manager, [seat2]) is True


class TestEdgeCases:
    """엣지 케이스 테스트"""

    def test_already_at_goal(self):
        """이미 골 라인에 있는 경우"""
        wall_manager = WallManager()
        start = Position(0, 4)
        goals = [Goal("row", 0)]

        distance = Pathfinder.get_shortest_distance(start, goals, wall_manager)

        assert distance == 0

    def test_path_from_corner(self):
        """코너에서 시작"""
        wall_manager = WallManager()
        start = Position(8, 0)
        goals = [Goal("row", 0)]

        exists = Pathfinder.has_path_to_goal(start, goals, wall_manager)

        assert exists is True


class TestMultiGoal:
    """다중 목표 / 좌석 목록 테스트"""

    def test_nearest_of_multiple_goals(self):
        """여러 목표 중 가장 가까운 목표까지의 거리"""
        goals = [Goal("row", 8), Goal("col", 8)]

        distance = Pathfinder.get_shortest_distance(Position(0, 0), goals, WallManager())

        assert distance == 8

    def test_start_on_goal_is_zero(self):
        """시작이 이미 목표 위면 거리 0"""
        goals = [Goal("row", 8), Goal("col", 8)]

        distance = Pathfinder.get_shortest_distance(Position(5, 8), goals, WallManager())

        assert distance == 0

    def test_empty_survivor_list_is_safe(self):
        """생존 좌석이 없으면 지킬 경로도 없다"""
        assert Pathfinder.can_place_wall_safely(WallManager(), []) is True
