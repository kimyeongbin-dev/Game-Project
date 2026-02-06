"""
Game Scenario Tests
복잡한 게임 시나리오 테스트
"""

import pytest
import sys
from pathlib import Path

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from games.game_Quoridor.core.game_state import GameState, GameStatus
from games.game_Quoridor.core.board import Position
from games.game_Quoridor.core.wall import Wall, Orientation


class TestCompleteGame:
    """완전한 게임 플로우 테스트"""

    def test_player1_wins_direct_path(self):
        """Player 1 직선 승리"""
        game = GameState()

        # Player 1이 8번 이동하여 승리
        moves = [(7, 4), (6, 4), (5, 4), (4, 4), (3, 4), (2, 4), (1, 4), (0, 4)]

        for i, (row, col) in enumerate(moves):
            # Player 1 이동
            success, msg = game.move_pawn(row, col)
            assert success, f"Move {i+1} failed: {msg}"

            if i < len(moves) - 1:  # 마지막 이동 전까지
                # Player 2 이동 (옆으로)
                p2_col = 4 + (1 if i % 2 == 0 else -1)
                if 0 <= p2_col <= 8:
                    game.move_pawn(i + 1, p2_col)
                else:
                    game.move_pawn(i + 1, 4)

        assert game.status == GameStatus.PLAYER1_WIN
        assert game.winner == 1

    def test_player2_wins(self):
        """Player 2 승리"""
        game = GameState()

        # Player 1: 벽만 설치
        game.place_wall(0, 0, "horizontal")

        # Player 2 이동
        for row in range(1, 9):
            game.move_pawn(row, 4)
            if row < 8:
                game.place_wall(row, row % 7, "vertical")

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
        game.player1._position = Position(3, 4)
        game.player2._position = Position(2, 4)

        valid_moves = game.get_valid_pawn_moves()

        # 상대 뒤로 점프 가능
        assert Position(1, 4) in valid_moves

    def test_diagonal_jump_wall_behind(self):
        """벽 뒤 대각선 점프"""
        game = GameState()

        game.player1._position = Position(3, 4)
        game.player2._position = Position(2, 4)

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

        game.player1._position = Position(1, 0)
        game.player2._position = Position(0, 0)

        valid_moves = game.get_valid_pawn_moves()

        # 상대 뒤는 보드 밖 -> 대각선만 가능
        assert Position(-1, 0) not in [m for m in valid_moves if hasattr(m, 'row')]


class TestEdgeCases:
    """엣지 케이스 테스트"""

    def test_move_after_win(self):
        """승리 후 이동 불가"""
        game = GameState()
        game.player1._position = Position(1, 4)
        game.move_pawn(0, 4)  # 승리

        assert game.status == GameStatus.PLAYER1_WIN

        # 추가 이동 불가
        success, _ = game.move_pawn(1, 4)
        assert success is False

    def test_wall_after_win(self):
        """승리 후 벽 설치 불가"""
        game = GameState()
        game.player1._position = Position(1, 4)
        game.move_pawn(0, 4)

        success, _ = game.place_wall(4, 4, "horizontal")
        assert success is False

    def test_all_walls_used(self):
        """모든 벽 사용"""
        game = GameState()

        for i in range(10):
            row = i % 8
            col = (i * 2) % 7
            success, _ = game.place_wall(row, col, "horizontal")
            if success:
                # 상대 턴
                game.move_pawn(game.current_player.position.row + (1 if game.current_turn == 2 else -1), 4)

        # 더 이상 벽 설치 불가
        assert game.player1.walls_remaining == 0 or game.player2.walls_remaining == 0


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

        copy1.move_pawn(6, 4)  # 직진
        copy2.move_pawn(1, 3)  # 측면

        # 두 복사본 상태 다름
        assert copy1.player2.position != copy2.player2.position
