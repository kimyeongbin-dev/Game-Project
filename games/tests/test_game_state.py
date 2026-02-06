"""
GameState Tests
게임 상태 관리 테스트
"""

import pytest
import sys
from pathlib import Path

# 프로젝트 루트 경로 추가
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from games.game_Quoridor.core.game_state import GameState, GameStatus, GameMode
from games.game_Quoridor.core.board import Position


class TestGameStateCreation:
    """게임 상태 생성 테스트"""

    def test_create_default_game(self):
        """기본 게임 생성"""
        game = GameState()

        assert game.game_id is not None
        assert game.status == GameStatus.IN_PROGRESS
        assert game.current_turn == 1
        assert game.turn_count == 0
        assert game.winner is None
        assert game.game_mode == GameMode.VS_AI

    def test_create_game_with_custom_names(self):
        """커스텀 플레이어명 게임 생성"""
        game = GameState(player1_name="Alice", player2_name="Bob")

        assert game.player1.name == "Alice"
        assert game.player2.name == "Bob"

    def test_create_local_2p_game(self):
        """로컬 2인 모드 게임 생성"""
        game = GameState(game_mode="local_2p")

        assert game.game_mode == GameMode.LOCAL_2P

    def test_initial_player_positions(self):
        """초기 플레이어 위치"""
        game = GameState()

        # Player 1: 하단 중앙 (8, 4)
        assert game.player1.position.row == 8
        assert game.player1.position.col == 4

        # Player 2: 상단 중앙 (0, 4)
        assert game.player2.position.row == 0
        assert game.player2.position.col == 4

    def test_initial_walls_remaining(self):
        """초기 벽 개수"""
        game = GameState()

        assert game.player1.walls_remaining == 10
        assert game.player2.walls_remaining == 10


class TestPawnMovement:
    """폰 이동 테스트"""

    def test_valid_move_forward(self):
        """유효한 전진 이동"""
        game = GameState()

        # Player 1: (8, 4) -> (7, 4)
        success, message = game.move_pawn(7, 4)

        assert success is True
        assert game.player1.position.row == 7
        assert game.player1.position.col == 4
        assert game.current_turn == 2
        assert game.turn_count == 1

    def test_invalid_move_too_far(self):
        """너무 먼 이동 (무효)"""
        game = GameState()

        # Player 1: (8, 4) -> (6, 4) - 2칸 이동 불가
        success, message = game.move_pawn(6, 4)

        assert success is False
        assert game.player1.position.row == 8  # 위치 변경 없음
        assert game.current_turn == 1  # 턴 변경 없음

    def test_invalid_move_out_of_bounds(self):
        """보드 범위 밖 이동 (무효)"""
        game = GameState()

        success, message = game.move_pawn(9, 4)

        assert success is False

    def test_move_after_game_finished(self):
        """게임 종료 후 이동 불가"""
        game = GameState()
        game.status = GameStatus.PLAYER1_WIN

        success, message = game.move_pawn(7, 4)

        assert success is False
        assert "finished" in message.lower()


class TestWallPlacement:
    """벽 설치 테스트"""

    def test_valid_wall_placement(self):
        """유효한 벽 설치"""
        game = GameState()

        success, message = game.place_wall(4, 4, "horizontal")

        assert success is True
        assert game.player1.walls_remaining == 9
        assert len(game.wall_manager.walls) == 1
        assert game.current_turn == 2

    def test_wall_placement_no_walls_remaining(self):
        """벽 없을 때 설치 불가"""
        game = GameState()
        game.player1._walls_remaining = 0

        success, message = game.place_wall(4, 4, "horizontal")

        assert success is False
        assert "no walls" in message.lower()

    def test_wall_placement_invalid_orientation(self):
        """잘못된 벽 방향"""
        game = GameState()

        success, message = game.place_wall(4, 4, "diagonal")

        assert success is False


class TestWinCondition:
    """승리 조건 테스트"""

    def test_player1_wins(self):
        """Player 1 승리"""
        game = GameState()
        # Player 1을 골 라인 바로 앞에 배치
        game.player1._position = Position(1, 4)

        success, message = game.move_pawn(0, 4)

        assert success is True
        assert game.status == GameStatus.PLAYER1_WIN
        assert game.winner == 1
        assert "wins" in message.lower()

    def test_player2_wins(self):
        """Player 2 승리"""
        game = GameState()
        # Player 1 이동 후 Player 2 턴
        game.move_pawn(7, 4)

        # Player 2를 골 라인 바로 앞에 배치
        game.player2._position = Position(7, 4)

        success, message = game.move_pawn(8, 4)

        assert success is True
        assert game.status == GameStatus.PLAYER2_WIN
        assert game.winner == 2


class TestSerialization:
    """직렬화/역직렬화 테스트"""

    def test_to_dict(self):
        """게임 상태 -> 딕셔너리"""
        game = GameState(player1_name="Test1", player2_name="Test2")

        data = game.to_dict()

        assert data["game_id"] == game.game_id
        assert data["status"] == "in_progress"
        assert data["current_turn"] == 1
        assert data["players"]["player1"]["name"] == "Test1"
        assert data["players"]["player2"]["name"] == "Test2"

    def test_from_dict(self):
        """딕셔너리 -> 게임 상태 복원"""
        original = GameState(player1_name="Original1", player2_name="Original2")
        original.move_pawn(7, 4)  # 한 수 진행

        data = original.to_dict()
        restored = GameState.from_dict(data)

        assert restored.game_id == original.game_id
        assert restored.current_turn == original.current_turn
        assert restored.turn_count == original.turn_count
        assert restored.player1.position == original.player1.position

    def test_serialization_with_walls(self):
        """벽이 있는 게임 직렬화"""
        game = GameState()
        game.place_wall(3, 3, "horizontal")

        data = game.to_dict()
        restored = GameState.from_dict(data)

        assert len(restored.wall_manager.walls) == 1
        assert restored.player1.walls_remaining == 9


class TestGameCopy:
    """게임 복사 테스트"""

    def test_deep_copy(self):
        """깊은 복사"""
        original = GameState()
        original.move_pawn(7, 4)

        copied = original.copy()

        # 복사본 수정이 원본에 영향 없어야 함
        copied.move_pawn(6, 4)

        assert original.player1.position.row == 7
        assert copied.player1.position.row == 6
        assert original.current_turn == 2
        assert copied.current_turn == 1  # 복사본은 턴 전환됨
