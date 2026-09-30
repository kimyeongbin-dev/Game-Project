"""
Game Scenario Tests
복잡한 게임 시나리오 테스트
"""

import pytest


from app.games.maze.core.game_state import GameState, GameStatus
from app.games.maze.core.board import Position
from app.games.maze.core.wall import Wall, Orientation


class TestCompleteGame:
    """완전한 게임 플로우 테스트"""

    def test_player1_wins_direct_path(self):
        """Player 1 직선 승리"""
        game = GameState()

        # Player 1이 4열을 따라 8번 이동하여 승리
        p1_moves = [(7, 4), (6, 4), (5, 4), (4, 4), (3, 4), (2, 4), (1, 4), (0, 4)]

        # Player 2는 3열로 비켜선 뒤 제자리에서 왕복 (Player 1의 경로/골 칸을 비움)
        p2_moves = [(0, 3), (1, 3), (0, 3), (1, 3), (0, 3), (1, 3), (0, 3)]

        for i, (row, col) in enumerate(p1_moves):
            success, msg = game.move_pawn(row, col)
            assert success, f"P1 move {i+1} -> ({row}, {col}) failed: {msg}"

            if i < len(p2_moves):
                p2_row, p2_col = p2_moves[i]
                success, msg = game.move_pawn(p2_row, p2_col)
                assert success, f"P2 move {i+1} -> ({p2_row}, {p2_col}) failed: {msg}"

        assert game.status == GameStatus.PLAYER1_WIN
        assert game.winner == 1

    def test_player2_wins(self):
        """Player 2 승리"""
        game = GameState()

        # Player 1은 P2의 골 칸 (8, 4)를 비켜준 뒤 벽만 설치
        success, msg = game.move_pawn(8, 3)
        assert success, f"P1 setup move failed: {msg}"

        # 수직 벽은 좌우 이동만 막으므로 두 플레이어의 세로 경로를 절대 차단하지 않음
        # (같은 열의 수직 벽은 슬롯이 겹치지 않도록 2행 간격으로 배치)
        p1_walls = [(0, 0), (2, 0), (4, 0), (6, 0), (0, 1), (2, 1), (4, 1)]

        # Player 2가 4열을 따라 8칸 내려가 승리, 그 사이 Player 1은 벽 설치
        for i, row in enumerate(range(1, 9)):
            success, msg = game.move_pawn(row, 4)
            assert success, f"P2 move -> ({row}, 4) failed: {msg}"

            if i < len(p1_walls):
                w_row, w_col = p1_walls[i]
                success, msg = game.place_wall(w_row, w_col, "vertical")
                assert success, f"P1 wall -> ({w_row}, {w_col}) failed: {msg}"

        assert game.status == GameStatus.PLAYER2_WIN
        assert game.winner == 2


class TestWallStrategy:
    """벽 전략 테스트"""

    def test_wall_blocks_direct_path(self):
        """벽이 직선 경로 차단"""
        game = GameState()

        # Player 1 전진
        game.move_pawn(7, 4)

        # Player 2 벽으로 차단
        game.place_wall(6, 3, "horizontal")
        game.place_wall(6, 5, "horizontal")

        # Player 1 더 이상 직선 이동 불가
        valid_moves = game.get_valid_pawn_moves()
        assert Position(6, 4) not in valid_moves

    def test_cannot_completely_block(self):
        """완전 차단 불가"""
        game = GameState()

        # 경로를 완전히 막는 벽 시도
        walls_placed = 0
        for row in range(7):
            for col in range(7):
                success, _ = game.place_wall(row, col, "horizontal")
                if success:
                    walls_placed += 1
                    # 다음 턴
                    game.move_pawn(game.player2.position.row + 1, 4)
                if walls_placed >= 10:
                    break
            if walls_placed >= 10:
                break

        # 게임은 여전히 진행 가능해야 함
        assert game.status == GameStatus.IN_PROGRESS


class TestJumpScenarios:
    """점프 시나리오 테스트"""

    def test_simple_jump(self):
        """단순 점프"""
        game = GameState()

        # 두 플레이어를 인접하게 배치
        game.player1.position = Position(3, 4)
        game.player2.position = Position(2, 4)

        valid_moves = game.get_valid_pawn_moves()

        # 상대 뒤로 점프 가능
        assert Position(1, 4) in valid_moves

    def test_diagonal_jump_wall_behind(self):
        """벽 뒤 대각선 점프"""
        game = GameState()

        game.player1.position = Position(3, 4)
        game.player2.position = Position(2, 4)

        # 상대 뒤에 벽
        game.wall_manager.add_wall(Wall(1, 3, Orientation.HORIZONTAL))
        game.wall_manager.add_wall(Wall(1, 4, Orientation.HORIZONTAL))

        valid_moves = game.get_valid_pawn_moves()

        # 직선 점프 불가
        assert Position(1, 4) not in valid_moves

        # 대각선 점프 가능
        diagonal_possible = Position(2, 3) in valid_moves or Position(2, 5) in valid_moves
        assert diagonal_possible

    def test_jump_at_edge(self):
        """가장자리에서 점프"""
        game = GameState()

        game.player1.position = Position(1, 0)
        game.player2.position = Position(0, 0)

        valid_moves = game.get_valid_pawn_moves()

        # 상대 뒤(-1, 0)는 보드 밖이라 직선 점프 불가 -> 대각선 점프만 가능
        assert Position(0, 1) in valid_moves

        # 모든 이동 후보는 보드 안이어야 함
        assert all(0 <= m.row <= 8 and 0 <= m.col <= 8 for m in valid_moves)


class TestEdgeCases:
    """엣지 케이스 테스트"""

    def test_move_after_win(self):
        """승리 후 이동 불가"""
        game = GameState()
        game.player1.position = Position(1, 4)
        game.player2.position = Position(0, 0)  # 골 칸을 비켜줌
        game.move_pawn(0, 4)  # 승리

        assert game.status == GameStatus.PLAYER1_WIN

        # 추가 이동 불가
        success, _ = game.move_pawn(1, 4)
        assert success is False

    def test_wall_after_win(self):
        """승리 후 벽 설치 불가"""
        game = GameState()
        game.player1.position = Position(1, 4)
        game.player2.position = Position(0, 0)  # 골 칸을 비켜줌
        game.move_pawn(0, 4)

        success, _ = game.place_wall(4, 4, "horizontal")
        assert success is False

    def test_all_walls_used(self):
        """모든 벽 사용"""
        game = GameState()

        # 수직 벽만 사용하면 세로 경로가 막히지 않아 10개를 모두 설치할 수 있음
        # (같은 열에서는 슬롯이 겹치지 않도록 2행 간격)
        p1_walls = [
            (0, 0), (2, 0), (4, 0), (6, 0),
            (0, 1), (2, 1), (4, 1), (6, 1),
            (0, 2), (2, 2),
        ]

        for i, (row, col) in enumerate(p1_walls):
            success, msg = game.place_wall(row, col, "vertical")
            assert success, f"P1 wall {i+1} -> ({row}, {col}) failed: {msg}"

            # Player 2는 0행/1행을 왕복하며 턴만 넘김
            p2_row = 1 if i % 2 == 0 else 0
            success, msg = game.move_pawn(p2_row, 4)
            assert success, f"P2 filler move -> ({p2_row}, 4) failed: {msg}"

        assert game.player1.walls_remaining == 0

        # 더 이상 벽 설치 불가
        success, message = game.place_wall(6, 2, "vertical")
        assert success is False
        assert "no walls" in message.lower()


class TestTurnManagement:
    """턴 관리 테스트"""

    def test_turn_switches_after_move(self):
        """이동 후 턴 전환"""
        game = GameState()
        assert game.current_turn == 1

        game.move_pawn(7, 4)
        assert game.current_turn == 2

        game.move_pawn(1, 4)
        assert game.current_turn == 1

    def test_turn_switches_after_wall(self):
        """벽 설치 후 턴 전환"""
        game = GameState()
        assert game.current_turn == 1

        game.place_wall(4, 4, "horizontal")
        assert game.current_turn == 2

    def test_turn_count_increments(self):
        """턴 카운트 증가"""
        game = GameState()
        assert game.turn_count == 0

        game.move_pawn(7, 4)
        assert game.turn_count == 1

        game.move_pawn(1, 4)
        assert game.turn_count == 2

    def test_failed_move_no_turn_switch(self):
        """실패한 이동은 턴 전환 없음"""
        game = GameState()

        game.move_pawn(5, 5)  # 무효한 이동

        assert game.current_turn == 1
        assert game.turn_count == 0


class TestGameCopy:
    """게임 복사 시나리오 테스트"""

    def test_copy_mid_game(self):
        """게임 중간 복사"""
        game = GameState()
        game.move_pawn(7, 4)
        game.place_wall(4, 4, "horizontal")
        game.move_pawn(6, 4)

        copied = game.copy()

        assert copied.turn_count == game.turn_count
        assert copied.player1.position == game.player1.position
        assert len(copied.wall_manager.walls) == len(game.wall_manager.walls)

    def test_copy_allows_different_paths(self):
        """복사본에서 다른 경로 가능"""
        game = GameState()
        game.move_pawn(7, 4)

        copy1 = game.copy()
        copy2 = game.copy()

        # 복사 시점 턴은 Player 2
        assert copy1.move_pawn(1, 4)[0] is True  # 전진
        assert copy2.move_pawn(0, 3)[0] is True  # 측면

        # 두 복사본 상태 다름
        assert copy1.player2.position != copy2.player2.position
