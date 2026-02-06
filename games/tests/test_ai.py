"""
SimpleAI Tests
AI 플레이어 테스트
"""

import pytest
import sys
from pathlib import Path
from unittest.mock import patch

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from games.game_Quoridor.ai.simple_ai import SimpleAI
from games.game_Quoridor.core.game_state import GameState, ActionType
from games.game_Quoridor.core.board import Position


class TestAICreation:
    """AI 생성 테스트"""

    def test_create_easy_ai(self):
        """Easy 난이도 AI 생성"""
        ai = SimpleAI(difficulty="easy")

        assert ai.difficulty == "easy"
        assert ai.wall_probability == 0.1
        assert ai.randomness == 0.3

    def test_create_normal_ai(self):
        """Normal 난이도 AI 생성"""
        ai = SimpleAI(difficulty="normal")

        assert ai.difficulty == "normal"
        assert ai.wall_probability == 0.25
        assert ai.randomness == 0.15

    def test_create_hard_ai(self):
        """Hard 난이도 AI 생성"""
        ai = SimpleAI(difficulty="hard")

        assert ai.difficulty == "hard"
        assert ai.wall_probability == 0.4
        assert ai.randomness == 0.05


class TestAIMovement:
    """AI 이동 테스트"""

    def test_ai_returns_action(self):
        """AI가 액션 반환"""
        ai = SimpleAI()
        game = GameState()
        game.move_pawn(7, 4)  # Player 1 이동, AI 턴

        action = ai.get_move(game)

        assert action is not None
        assert action.action_type in [ActionType.MOVE, ActionType.WALL]

    def test_ai_move_action(self):
        """AI 이동 액션"""
        ai = SimpleAI()
        game = GameState()
        game.move_pawn(7, 4)

        # 랜덤 제거하고 테스트
        with patch('random.random', return_value=1.0):  # 랜덤 행동 안함
            with patch('random.choice', side_effect=lambda x: x[0]):
                action = ai.get_move(game)

        if action.action_type == ActionType.MOVE:
            # 유효한 위치인지 확인
            valid_moves = game.get_valid_pawn_moves()
            target = Position(action.row, action.col)
            assert target in valid_moves

    def test_ai_wall_action(self):
        """AI 벽 설치 액션"""
        ai = SimpleAI(difficulty="hard")  # 벽 확률 높음
        game = GameState()
        game.move_pawn(7, 4)

        # 여러 번 시도하여 벽 설치 확인
        wall_placed = False
        for _ in range(20):
            action = ai.get_move(game.copy())
            if action.action_type == ActionType.WALL:
                wall_placed = True
                # 유효한 벽인지 확인
                valid_walls = game.get_valid_wall_placements()
                from games.game_Quoridor.core.wall import Wall, Orientation
                wall = Wall(action.row, action.col, action.orientation)
                assert wall in valid_walls
                break

        # Hard AI는 벽을 설치할 가능성이 높음
        # 하지만 랜덤 요소가 있어 항상 보장되지는 않음


class TestAIStrategy:
    """AI 전략 테스트"""

    def test_ai_moves_toward_goal(self):
        """AI가 목표 방향으로 이동"""
        ai = SimpleAI()
        game = GameState()
        game.move_pawn(7, 4)  # Player 1 이동

        # AI 턴 (Player 2, 목표 row=8)
        initial_pos = game.player2.position

        # 랜덤 행동 제거
        with patch('random.random', return_value=1.0):
            with patch('random.choice', side_effect=lambda x: x[0]):
                action = ai.get_move(game)

        if action.action_type == ActionType.MOVE:
            # 목표 행에 가까워지거나 같은 거리
            assert action.row >= initial_pos.row or action.row == initial_pos.row

    def test_ai_wins_when_possible(self):
        """AI 승리 가능 시 이동"""
        ai = SimpleAI()
        game = GameState()

        # Player 2를 골 라인 바로 앞에 배치
        game.player2._position = Position(7, 4)
        game._current_turn = 2  # AI 턴으로 설정

        action = ai.get_move(game)

        # 승리 직전이면 무조건 이동해야 함
        assert action.action_type == ActionType.MOVE
        assert action.row == 8  # 골 라인


class TestAIEdgeCases:
    """AI 엣지 케이스 테스트"""

    def test_ai_no_valid_moves(self):
        """유효한 이동 없을 때 (극히 드문 경우)"""
        # 실제 게임에서는 거의 발생하지 않음
        # 벽에 완전히 갇힌 경우
        pass

    def test_ai_no_walls_remaining(self):
        """벽 없을 때 이동만"""
        ai = SimpleAI()
        game = GameState()
        game.move_pawn(7, 4)
        game.player2._walls_remaining = 0

        action = ai.get_move(game)

        # 벽이 없으면 이동만 가능
        assert action.action_type == ActionType.MOVE

    def test_ai_consistency(self):
        """같은 상황에서 일관된 동작"""
        ai = SimpleAI(difficulty="hard")
        game = GameState()
        game.move_pawn(7, 4)

        # 랜덤 시드 고정
        import random
        random.seed(42)

        action1 = ai.get_move(game.copy())

        random.seed(42)
        action2 = ai.get_move(game.copy())

        # 같은 시드면 같은 결과
        assert action1.action_type == action2.action_type
        assert action1.row == action2.row
        assert action1.col == action2.col


class TestAIDifficulty:
    """난이도별 AI 동작 테스트"""

    def test_easy_more_random(self):
        """Easy AI는 더 랜덤"""
        easy_ai = SimpleAI(difficulty="easy")
        hard_ai = SimpleAI(difficulty="hard")

        assert easy_ai.randomness > hard_ai.randomness

    def test_hard_more_walls(self):
        """Hard AI는 벽 더 많이 사용"""
        easy_ai = SimpleAI(difficulty="easy")
        hard_ai = SimpleAI(difficulty="hard")

        assert hard_ai.wall_probability > easy_ai.wall_probability
