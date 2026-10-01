"""
Game Scenario Tests
복잡한 게임 시나리오 테스트 (duel)
"""

import pytest


from app.games.maze.core.game_state import GameState, GameStatus, EndReason
from app.games.maze.core.board import Position
from app.games.maze.core.move_validator import Rejection


class TestCompleteGame:
    """완전한 게임 플로우 테스트"""

    def test_seat1_wins_direct_path(self):
        """seat 1 직선 승리 — seat 2 와 같은 열을 지나며 겹쳐도 막히지 않는다"""
        game = GameState()

        # seat 1 이 4열을 따라 8번 이동하여 승리
        s1_moves = [(7, 4), (6, 4), (5, 4), (4, 4), (3, 4), (2, 4), (1, 4), (0, 4)]

        # seat 2 도 4열을 따라 내려온다 — 중간에 seat 1 과 마주치고 겹친다
        s2_moves = [(1, 4), (2, 4), (3, 4), (4, 4), (5, 4), (6, 4), (7, 4)]

        for i, (row, col) in enumerate(s1_moves):
            rejection = game.move(1, row, col)
            assert rejection is None, f"seat 1 move {i+1} -> ({row}, {col}) failed: {rejection}"

            if i < len(s2_moves):
                s2_row, s2_col = s2_moves[i]
                rejection = game.move(2, s2_row, s2_col)
                assert rejection is None, f"seat 2 move {i+1} -> ({s2_row}, {s2_col}) failed: {rejection}"

        assert game.status == GameStatus.FINISHED
        assert game.end_reason == EndReason.GOAL_REACHED
        assert game.winner_seat_no == 1

    def test_seat2_wins(self):
        """seat 2 승리"""
        game = GameState()

        # seat 1 은 수직 벽만 설치 — 세로 경로를 절대 차단하지 않는다
        # (같은 열의 수직 벽은 슬롯이 겹치지 않도록 2행 간격으로 배치)
        s1_walls = [(0, 0), (2, 0), (4, 0), (6, 0), (0, 1), (2, 1), (4, 1), (6, 1)]

        # seat 2 가 4열을 따라 8칸 내려가 승리. seat 1 이 선 (8, 4) 도 그냥 들어간다
        for i, row in enumerate(range(1, 9)):
            w_row, w_col = s1_walls[i]
            rejection = game.place_wall(1, w_row, w_col, "vertical")
            assert rejection is None, f"seat 1 wall -> ({w_row}, {w_col}) failed: {rejection}"

            rejection = game.move(2, row, 4)
            assert rejection is None, f"seat 2 move -> ({row}, 4) failed: {rejection}"

        assert game.end_reason == EndReason.GOAL_REACHED
        assert game.winner_seat_no == 2


class TestWallStrategy:
    """벽 전략 테스트"""

    def test_wall_blocks_direct_path(self):
        """벽이 직선 경로 차단"""
        game = GameState()

        game.move(1, 7, 4)
        game.place_wall(2, 6, 3, "horizontal")  # (6,3)-(7,3), (6,4)-(7,4) 차단

        valid_moves = game.get_valid_pawn_moves()
        assert Position(6, 4) not in valid_moves

    def test_cannot_completely_block(self):
        """완전 차단 불가 — 마지막 통로를 닫는 벽은 wall_blocks_path"""
        game = GameState()

        # seat 1 이 0행 바로 아래 col 0~7 에 가로벽을 깐다. seat 2 는 0행 안에서 좌우 왕복
        for i, col in enumerate((0, 2, 4, 6)):
            assert game.place_wall(1, 0, col, "horizontal") is None
            assert game.move(2, 0, 3 if i % 2 == 0 else 4) is None

        # seat 2 의 유일한 출구는 (0,8)→(1,8). 수직벽 (0,7) 이 (0,7)-(0,8) 을 막으면 갇힌다
        assert game.place_wall(1, 0, 7, "vertical") == Rejection.WALL_BLOCKS_PATH
        assert game.wall_rejections == 1
        assert game.status == GameStatus.IN_PROGRESS
        assert game.get_player_distance_to_goal(2) > 0


class TestEdgeCases:
    """엣지 케이스 테스트"""

    def _won_game(self) -> GameState:
        game = GameState()
        game.seat(1).position = Position(1, 4)
        game.move(1, 0, 4)  # 승리
        return game

    def test_move_after_win(self):
        """승리 후 이동 불가"""
        game = self._won_game()

        assert game.status == GameStatus.FINISHED
        assert game.move(2, 1, 4) == Rejection.GAME_ALREADY_ENDED

    def test_wall_after_win(self):
        """승리 후 벽 설치 불가"""
        game = self._won_game()

        assert game.place_wall(2, 4, 4, "horizontal") == Rejection.GAME_ALREADY_ENDED

    def test_all_walls_used(self):
        """모든 벽 사용"""
        game = GameState()

        # 수직 벽만 사용하면 세로 경로가 막히지 않아 10개를 모두 설치할 수 있음
        # (같은 열에서는 슬롯이 겹치지 않도록 2행 간격)
        s1_walls = [
            (0, 0), (2, 0), (4, 0), (6, 0),
            (0, 1), (2, 1), (4, 1), (6, 1),
            (0, 2), (2, 2),
        ]

        for i, (row, col) in enumerate(s1_walls):
            rejection = game.place_wall(1, row, col, "vertical")
            assert rejection is None, f"seat 1 wall {i+1} -> ({row}, {col}) failed: {rejection}"

            # seat 2 는 0행/1행을 왕복하며 턴만 넘김
            s2_row = 1 if i % 2 == 0 else 0
            rejection = game.move(2, s2_row, 4)
            assert rejection is None, f"seat 2 filler move -> ({s2_row}, 4) failed: {rejection}"

        assert game.seat(1).walls_remaining == 0
        assert game.place_wall(1, 6, 2, "vertical") == Rejection.NO_WALLS_REMAINING


class TestTurnManagement:
    """턴 관리 테스트"""

    def test_turn_switches_after_move(self):
        """이동 후 턴 전환"""
        game = GameState()
        assert game.current_seat_no == 1

        game.move(1, 7, 4)
        assert game.current_seat_no == 2

        game.move(2, 1, 4)
        assert game.current_seat_no == 1

    def test_turn_switches_after_wall(self):
        """벽 설치 후 턴 전환"""
        game = GameState()

        game.place_wall(1, 4, 4, "horizontal")
        assert game.current_seat_no == 2

    def test_turn_count_increments(self):
        """턴 카운트 증가"""
        game = GameState()
        assert game.turn_count == 0

        game.move(1, 7, 4)
        assert game.turn_count == 1

        game.move(2, 1, 4)
        assert game.turn_count == 2

    def test_failed_move_no_turn_switch(self):
        """실패한 이동은 턴 전환 없음"""
        game = GameState()

        game.move(1, 5, 5)  # 무효한 이동

        assert game.current_seat_no == 1
        assert game.turn_count == 0

    def test_failed_wall_does_not_consume_turn(self):
        """거절된 벽 시도는 턴을 소모하지 않는다 (§7)"""
        game = GameState()
        game.place_wall(1, 4, 4, "horizontal")

        game.place_wall(2, 4, 4, "vertical")  # 교차 → 거절

        assert game.current_seat_no == 2
        assert game.seat(2).turns_taken == 0


class TestGameCopy:
    """게임 복사 시나리오 테스트"""

    def test_copy_mid_game(self):
        """게임 중간 복사"""
        game = GameState()
        game.move(1, 7, 4)
        game.place_wall(2, 4, 4, "horizontal")
        game.move(1, 6, 4)

        copied = game.copy()

        assert copied.turn_count == game.turn_count
        assert copied.seat(1).position == game.seat(1).position
        assert len(copied.wall_manager.walls) == len(game.wall_manager.walls)

    def test_copy_allows_different_paths(self):
        """복사본에서 다른 경로 가능"""
        game = GameState()
        game.move(1, 7, 4)

        copy1 = game.copy()
        copy2 = game.copy()

        # 복사 시점 차례는 seat 2
        assert copy1.move(2, 1, 4) is None  # 전진
        assert copy2.move(2, 0, 3) is None  # 측면

        assert copy1.seat(2).position != copy2.seat(2).position
