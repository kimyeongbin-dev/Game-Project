"""
GameState Tests
게임 상태 관리 테스트 (duel 기준 — 좌석 수 일반화는 test_seat_scaling.py)
"""

import json

import pytest

from app.games.maze.core.game_state import (
    GameState, GameStatus, EndReason, SCHEMA_VERSION,
)
from app.games.maze.core.board import Goal, Position
from app.games.maze.core.move_validator import Rejection


class TestGameStateCreation:
    """게임 상태 생성 테스트"""

    def test_create_default_game(self):
        """기본 게임은 duel"""
        game = GameState()

        assert game.game_id is not None
        assert game.mode == "duel"
        assert game.status == GameStatus.IN_PROGRESS
        assert game.end_reason is None
        assert game.winner_seat_no is None
        assert game.current_seat_no == 1
        assert game.turn_count == 0
        assert game.wall_rejections == 0
        assert [p.seat_no for p in game.seats] == [1, 2]

    def test_unknown_mode(self):
        """배치 테이블에 없는 모드"""
        with pytest.raises(ValueError):
            GameState("solo")

    def test_initial_seat_positions(self):
        """초기 좌석 위치·목표"""
        game = GameState()

        assert game.seat(1).position == Position(8, 4)
        assert game.seat(1).goals == (Goal("row", 0),)
        assert game.seat(2).position == Position(0, 4)
        assert game.seat(2).goals == (Goal("row", 8),)

    def test_initial_walls_remaining(self):
        """초기 벽 개수"""
        game = GameState()

        assert game.seat(1).walls_remaining == 10
        assert game.seat(2).walls_remaining == 10

    def test_invalid_seat(self):
        game = GameState()
        with pytest.raises(ValueError):
            game.seat(3)


class TestPawnMovement:
    """말 이동 테스트"""

    def test_valid_move_forward(self):
        """유효한 전진 이동"""
        game = GameState()

        assert game.move(1, 7, 4) is None
        assert game.seat(1).position == Position(7, 4)
        assert game.seat(1).turns_taken == 1
        assert game.current_seat_no == 2
        assert game.turn_count == 1

    def test_invalid_move_too_far(self):
        """두 칸 이동 (무효)"""
        game = GameState()

        assert game.move(1, 6, 4) == Rejection.INVALID_MOVE
        assert game.seat(1).position == Position(8, 4)  # 위치 변경 없음
        assert game.current_seat_no == 1  # 턴 변경 없음
        assert game.turn_count == 0

    def test_invalid_move_out_of_bounds(self):
        """보드 범위 밖 이동 (무효)"""
        game = GameState()

        assert game.move(1, 9, 4) == Rejection.INVALID_MOVE

    def test_not_your_turn(self):
        """차례가 아닌 좌석의 행동은 엔진이 거절한다"""
        game = GameState()

        assert game.move(2, 1, 4) == Rejection.NOT_YOUR_TURN
        assert game.seat(2).position == Position(0, 4)

    def test_move_after_game_finished(self):
        """게임 종료 후 이동 불가"""
        game = GameState()
        game.eliminate(2, "surrender")

        assert game.move(1, 7, 4) == Rejection.GAME_ALREADY_ENDED


class TestWallPlacement:
    """벽 설치 테스트"""

    def test_valid_wall_placement(self):
        """유효한 벽 설치"""
        game = GameState()

        assert game.place_wall(1, 4, 4, "horizontal") is None
        assert game.seat(1).walls_remaining == 9
        assert len(game.wall_manager.walls) == 1
        assert game.current_seat_no == 2

    def test_wall_placement_no_walls_remaining(self):
        """벽 없을 때 설치 불가"""
        game = GameState()
        game.seat(1).walls_remaining = 0

        assert game.place_wall(1, 4, 4, "horizontal") == Rejection.NO_WALLS_REMAINING

    def test_wall_placement_invalid_orientation(self):
        """잘못된 벽 방향"""
        game = GameState()

        assert game.place_wall(1, 4, 4, "diagonal") == Rejection.INVALID_WALL_POSITION

    def test_wall_placement_out_of_range(self):
        """벽 좌표 범위 밖 (0-7)"""
        game = GameState()

        assert game.place_wall(1, 8, 0, "horizontal") == Rejection.INVALID_WALL_POSITION


class TestProbeLimit:
    """턴당 거절 카운터 (maze.md §7)"""

    def _game_with_wall(self) -> GameState:
        game = GameState()
        game.place_wall(1, 4, 4, "horizontal")  # seat 1 → seat 2 차례
        return game

    def test_overlap_and_cross_are_counted(self):
        """기존 벽과 겹침·교차는 숨은 벽을 드러내므로 센다"""
        game = self._game_with_wall()

        assert game.place_wall(2, 4, 4, "horizontal") == Rejection.INVALID_WALL_POSITION
        assert game.place_wall(2, 4, 4, "vertical") == Rejection.INVALID_WALL_POSITION
        assert game.wall_rejections == 2

    def test_out_of_range_is_not_counted(self):
        """범위 밖 좌표·방향값 무효는 정보가 없으므로 세지 않는다"""
        game = self._game_with_wall()

        game.place_wall(2, 9, 9, "horizontal")
        game.place_wall(2, 3, 3, "diagonal")
        assert game.wall_rejections == 0

    def test_third_rejection_locks_walls(self):
        """2회까지 허용, 3회째 거절은 원래 코드를 주며 잠그고, 이후는 probe_limit_exceeded"""
        game = self._game_with_wall()

        for _ in range(3):
            assert game.place_wall(2, 4, 4, "horizontal") == Rejection.INVALID_WALL_POSITION
        assert game.walls_locked is True

        # 정상 자리도 잠김
        assert game.place_wall(2, 1, 1, "horizontal") == Rejection.PROBE_LIMIT_EXCEEDED
        assert game.get_valid_wall_placements() == []

        # 이동은 가능하다
        assert game.move(2, 1, 4) is None

    def test_counter_resets_on_turn_change(self):
        game = self._game_with_wall()

        for _ in range(3):
            game.place_wall(2, 4, 4, "horizontal")
        game.move(2, 1, 4)

        assert game.wall_rejections == 0
        assert game.place_wall(1, 1, 1, "horizontal") is None


class TestWinCondition:
    """승리 조건 테스트"""

    def test_seat1_reaches_goal(self):
        """seat 1 도달"""
        game = GameState()
        game.seat(1).position = Position(1, 4)

        assert game.move(1, 0, 4) is None
        assert game.status == GameStatus.FINISHED
        assert game.end_reason == EndReason.GOAL_REACHED
        assert game.winner_seat_no == 1

    def test_reach_goal_cell_occupied_by_other_piece(self):
        """목표 칸에 다른 말이 서 있어도 들어가 도달한다 — 목표 봉쇄 불가 (§5)"""
        game = GameState()
        game.seat(1).position = Position(1, 4)
        # seat 2 는 (0, 4) 에서 시작 — seat 1 의 목표 칸 위

        assert game.move(1, 0, 4) is None
        assert game.winner_seat_no == 1

    def test_seat2_reaches_goal(self):
        """seat 2 도달"""
        game = GameState()
        game.move(1, 7, 4)
        game.seat(2).position = Position(7, 3)

        assert game.move(2, 8, 3) is None
        assert game.end_reason == EndReason.GOAL_REACHED
        assert game.winner_seat_no == 2


class TestElimination:
    """탈락 (maze.md §9)"""

    def test_surrender_in_duel_is_last_standing(self):
        """2인전은 한 명 탈락으로 last_standing 이 자동 성립"""
        game = GameState()

        assert game.eliminate(1, "surrender") is None
        assert game.end_reason == EndReason.LAST_STANDING
        assert game.winner_seat_no == 2
        assert game.seat(1).eliminated_order == 1
        assert game.seat(1).elimination_reason == "surrender"

    def test_invalid_reason(self):
        game = GameState()
        with pytest.raises(ValueError):
            game.eliminate(1, "rage_quit")

    def test_eliminate_after_end(self):
        game = GameState()
        game.eliminate(1, "time_forfeit")

        assert game.eliminate(2, "surrender") == Rejection.GAME_ALREADY_ENDED


class TestSerialization:
    """직렬화/역직렬화 — to_dict() 는 Redis game:<id>:state 값 전체"""

    def test_to_dict_shape(self):
        game = GameState()
        data = game.to_dict()

        assert data["schema_version"] == SCHEMA_VERSION
        assert data["mode"] == "duel"
        assert data["status"] == "in_progress"
        assert data["current_seat_no"] == 1
        assert data["seats"][0] == {
            "seat_no": 1,
            "position": {"row": 8, "col": 4},
            "goals": [{"axis": "row", "value": 0}],
            "walls_remaining": 10,
            "turns_taken": 0,
            "eliminated_order": None,
            "elimination_reason": None,
        }
        # 파생값·정체성은 담지 않는다
        for absent in ("players", "winner", "current_turn", "name"):
            assert absent not in data
        assert "name" not in data["seats"][0]

    def test_roundtrip_mid_game(self):
        """벽·거절 카운터·턴을 포함한 왕복 (JSON 문자열 경유)"""
        original = GameState()
        original.move(1, 7, 4)
        original.place_wall(2, 3, 3, "horizontal")
        original.place_wall(1, 3, 3, "horizontal")  # 겹침 → 카운터 1

        restored = GameState.from_dict(json.loads(json.dumps(original.to_dict())))

        assert restored.to_dict() == original.to_dict()
        assert restored.wall_rejections == 1
        assert len(restored.wall_manager.walls) == 1

    def test_roundtrip_finished_game(self):
        original = GameState()
        original.eliminate(2, "disconnect_forfeit")

        restored = GameState.from_dict(original.to_dict())

        assert restored.end_reason == EndReason.LAST_STANDING
        assert restored.seat(2).is_eliminated is True
        assert restored.to_dict() == original.to_dict()

    @pytest.mark.parametrize("version", [None, 0, SCHEMA_VERSION + 1])
    def test_rejects_other_schema_version(self, version):
        data = GameState().to_dict()
        data["schema_version"] = version

        with pytest.raises(ValueError):
            GameState.from_dict(data)

    def test_from_dict_does_not_consult_layout_table(self, monkeypatch):
        """테이블이 바뀌어도(모드 행이 사라져도) 진행 중 게임은 복원된다"""
        from app.games.maze.core import layouts

        data = GameState().to_dict()
        monkeypatch.delitem(layouts.LAYOUTS, "duel")

        assert GameState.from_dict(data).to_dict() == data


class TestGameCopy:
    """게임 복사 테스트"""

    def test_deep_copy(self):
        """깊은 복사"""
        original = GameState()
        original.move(1, 7, 4)

        copied = original.copy()
        copied.move(2, 1, 4)

        assert original.seat(2).position == Position(0, 4)
        assert copied.seat(2).position == Position(1, 4)
        assert original.current_seat_no == 2
        assert copied.current_seat_no == 1
