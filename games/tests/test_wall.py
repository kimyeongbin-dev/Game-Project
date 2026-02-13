"""
Wall Tests
벽 및 WallManager 테스트
"""

import pytest
import sys
from pathlib import Path

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from games.game_Quoridor.core.wall import Wall, WallManager, Orientation
from games.game_Quoridor.core.board import Position


class TestWallCreation:
    """Wall 생성 테스트"""

    def test_create_horizontal_wall(self):
        """수평 벽 생성"""
        wall = Wall(4, 4, Orientation.HORIZONTAL)

        assert wall.row == 4
        assert wall.col == 4
        assert wall.orientation == Orientation.HORIZONTAL

    def test_create_vertical_wall(self):
        """수직 벽 생성"""
        wall = Wall(4, 4, Orientation.VERTICAL)

        assert wall.orientation == Orientation.VERTICAL

    def test_wall_corners(self):
        """코너 위치 벽"""
        corners = [
            Wall(0, 0, Orientation.HORIZONTAL),
            Wall(0, 0, Orientation.VERTICAL),
            Wall(7, 7, Orientation.HORIZONTAL),
            Wall(7, 7, Orientation.VERTICAL)
        ]

        for wall in corners:
            assert 0 <= wall.row <= 7
            assert 0 <= wall.col <= 7

    def test_invalid_wall_position(self):
        """잘못된 벽 위치"""
        with pytest.raises(ValueError):
            Wall(8, 4, Orientation.HORIZONTAL)

        with pytest.raises(ValueError):
            Wall(4, 8, Orientation.HORIZONTAL)

        with pytest.raises(ValueError):
            Wall(-1, 4, Orientation.HORIZONTAL)


class TestWallBlocking:
    """벽 차단 테스트"""

    def test_horizontal_wall_blocks_vertical_movement(self):
        """수평 벽은 상하 이동 차단"""
        wall = Wall(4, 4, Orientation.HORIZONTAL)
        blocked = wall.get_blocked_edges()

        # (4, 4) <-> (5, 4) 차단
        assert ((4, 4), (5, 4)) in blocked
        assert ((5, 4), (4, 4)) in blocked

        # (4, 5) <-> (5, 5) 차단
        assert ((4, 5), (5, 5)) in blocked
        assert ((5, 5), (4, 5)) in blocked

    def test_vertical_wall_blocks_horizontal_movement(self):
        """수직 벽은 좌우 이동 차단"""
        wall = Wall(4, 4, Orientation.VERTICAL)
        blocked = wall.get_blocked_edges()

        # (4, 4) <-> (4, 5) 차단
        assert ((4, 4), (4, 5)) in blocked
        assert ((4, 5), (4, 4)) in blocked

        # (5, 4) <-> (5, 5) 차단
        assert ((5, 4), (5, 5)) in blocked
        assert ((5, 5), (5, 4)) in blocked


class TestWallIntersection:
    """벽 교차 테스트"""

    def test_same_position_same_orientation(self):
        """같은 위치, 같은 방향 (겹침)"""
        wall1 = Wall(4, 4, Orientation.HORIZONTAL)
        wall2 = Wall(4, 4, Orientation.HORIZONTAL)

        assert wall1.intersects_with(wall2) is True

    def test_same_position_different_orientation(self):
        """같은 위치, 다른 방향 (교차)"""
        wall1 = Wall(4, 4, Orientation.HORIZONTAL)
        wall2 = Wall(4, 4, Orientation.VERTICAL)

        assert wall1.intersects_with(wall2) is True

    def test_adjacent_horizontal_walls(self):
        """인접한 수평 벽 (겹침)"""
        wall1 = Wall(4, 4, Orientation.HORIZONTAL)
        wall2 = Wall(4, 5, Orientation.HORIZONTAL)

        assert wall1.intersects_with(wall2) is True

    def test_adjacent_vertical_walls(self):
        """인접한 수직 벽 (겹침)"""
        wall1 = Wall(4, 4, Orientation.VERTICAL)
        wall2 = Wall(5, 4, Orientation.VERTICAL)

        assert wall1.intersects_with(wall2) is True

    def test_non_intersecting_walls(self):
        """교차하지 않는 벽"""
        wall1 = Wall(0, 0, Orientation.HORIZONTAL)
        wall2 = Wall(7, 7, Orientation.VERTICAL)

        assert wall1.intersects_with(wall2) is False


class TestWallSerialization:
    """벽 직렬화 테스트"""

    def test_to_dict(self):
        """딕셔너리 변환"""
        wall = Wall(4, 4, Orientation.HORIZONTAL)

        data = wall.to_dict()

        assert data["row"] == 4
        assert data["col"] == 4
        assert data["orientation"] == "horizontal"

    def test_from_dict(self):
        """딕셔너리에서 생성"""
        data = {"row": 3, "col": 5, "orientation": "vertical"}

        wall = Wall.from_dict(data)

        assert wall.row == 3
        assert wall.col == 5
        assert wall.orientation == Orientation.VERTICAL


class TestWallManager:
    """WallManager 테스트"""

    def test_empty_manager(self):
        """빈 매니저"""
        manager = WallManager()

        assert len(manager.walls) == 0

    def test_add_wall(self):
        """벽 추가"""
        manager = WallManager()
        wall = Wall(4, 4, Orientation.HORIZONTAL)

        result = manager.add_wall(wall)

        assert result is True
        assert len(manager.walls) == 1

    def test_add_multiple_walls(self):
        """여러 벽 추가"""
        manager = WallManager()

        manager.add_wall(Wall(0, 0, Orientation.HORIZONTAL))
        manager.add_wall(Wall(2, 2, Orientation.VERTICAL))
        manager.add_wall(Wall(4, 4, Orientation.HORIZONTAL))

        assert len(manager.walls) == 3

    def test_cannot_add_overlapping_wall(self):
        """겹치는 벽 추가 불가"""
        manager = WallManager()
        manager.add_wall(Wall(4, 4, Orientation.HORIZONTAL))

        result = manager.add_wall(Wall(4, 4, Orientation.HORIZONTAL))

        assert result is False
        assert len(manager.walls) == 1

    def test_cannot_add_crossing_wall(self):
        """교차하는 벽 추가 불가"""
        manager = WallManager()
        manager.add_wall(Wall(4, 4, Orientation.HORIZONTAL))

        result = manager.add_wall(Wall(4, 4, Orientation.VERTICAL))

        assert result is False

    def test_can_place_wall(self):
        """벽 설치 가능 확인"""
        manager = WallManager()

        assert manager.can_place_wall(Wall(4, 4, Orientation.HORIZONTAL)) is True

        manager.add_wall(Wall(4, 4, Orientation.HORIZONTAL))

        assert manager.can_place_wall(Wall(4, 4, Orientation.VERTICAL)) is False


class TestWallManagerBlocking:
    """WallManager 차단 테스트"""

    def test_is_move_blocked(self):
        """이동 차단 확인"""
        manager = WallManager()
        manager.add_wall(Wall(4, 4, Orientation.HORIZONTAL))

        # 차단된 이동
        assert manager.is_move_blocked(Position(4, 4), Position(5, 4)) is True

        # 차단되지 않은 이동
        assert manager.is_move_blocked(Position(4, 4), Position(4, 5)) is False

    def test_multiple_walls_blocking(self):
        """여러 벽 차단"""
        manager = WallManager()
        manager.add_wall(Wall(4, 3, Orientation.HORIZONTAL))
        manager.add_wall(Wall(4, 5, Orientation.HORIZONTAL))

        # 둘 다 차단
        assert manager.is_move_blocked(Position(4, 3), Position(5, 3)) is True
        assert manager.is_move_blocked(Position(4, 5), Position(5, 5)) is True


class TestWallManagerCopy:
    """WallManager 복사 테스트"""

    def test_copy(self):
        """매니저 복사"""
        manager = WallManager()
        manager.add_wall(Wall(4, 4, Orientation.HORIZONTAL))

        copied = manager.copy()

        assert len(copied.walls) == 1
        assert copied.walls[0] == manager.walls[0]

    def test_copy_independence(self):
        """복사본 독립성"""
        manager = WallManager()
        manager.add_wall(Wall(4, 4, Orientation.HORIZONTAL))

        copied = manager.copy()
        copied.add_wall(Wall(0, 0, Orientation.VERTICAL))

        assert len(manager.walls) == 1
        assert len(copied.walls) == 2


class TestWallManagerRemove:
    """벽 제거 테스트"""

    def test_remove_last_wall(self):
        """마지막 벽 제거"""
        manager = WallManager()
        wall1 = Wall(0, 0, Orientation.HORIZONTAL)
        wall2 = Wall(4, 4, Orientation.VERTICAL)

        manager.add_wall(wall1)
        manager.add_wall(wall2)

        removed = manager.remove_last_wall()

        assert removed == wall2
        assert len(manager.walls) == 1

    def test_remove_from_empty(self):
        """빈 매니저에서 제거"""
        manager = WallManager()

        removed = manager.remove_last_wall()

        assert removed is None

    def test_remove_restores_blocking(self):
        """제거 후 차단 해제"""
        manager = WallManager()
        wall = Wall(4, 4, Orientation.HORIZONTAL)
        manager.add_wall(wall)

        # 차단됨
        assert manager.is_move_blocked(Position(4, 4), Position(5, 4)) is True

        manager.remove_last_wall()

        # 차단 해제
        assert manager.is_move_blocked(Position(4, 4), Position(5, 4)) is False
