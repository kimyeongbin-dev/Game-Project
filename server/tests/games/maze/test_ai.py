"""
SimpleAI Tests
AI 플레이어 테스트
"""

import random

import pytest


from app.games.maze.ai.simple_ai import SimpleAI
from app.games.maze.core.game_state import GameState, ActionType
from app.games.maze.core.board import Position, reaches_any
from app.games.maze.core.pathfinder import Pathfinder


class StubRandom(random.Random):
    """random() 은 고정값, choice()·sample() 은 앞에서부터 — AI 를 결정적으로 만든다"""

    def __init__(self, value: float):
        super().__init__(0)
        self._value = value

    def random(self):
        return self._value

    def choice(self, seq):
        return seq[0]

    def sample(self, population, k, **kwargs):
        return list(population)[:k]


class TestAICreation:
    """AI 생성 테스트"""

    def test_create_easy_ai(self):
        ai = SimpleAI(difficulty="easy")
        assert ai.difficulty == "easy"
        assert ai.wall_probability == 0.1
        assert ai.randomness == 0.3

    def test_create_normal_ai(self):
        ai = SimpleAI(difficulty="normal")
        assert ai.difficulty == "normal"
        assert ai.wall_probability == 0.25
        assert ai.randomness == 0.15

    def test_create_hard_ai(self):
        ai = SimpleAI(difficulty="hard")
        assert ai.difficulty == "hard"
        assert ai.wall_probability == 0.4
        assert ai.randomness == 0.05


class TestAIDecision:
    """AI 의사결정 테스트"""

    def test_ai_returns_action(self):
        """AI 가 행동을 반환하고, 그 행동은 엔진이 수락한다"""
        ai = SimpleAI(rng=random.Random(0))
        game = GameState()
        game.move(1, 7, 4)

        action = ai.get_move(game)

        assert action is not None
        assert action.action_type in (ActionType.MOVE, ActionType.WALL)

    def test_ai_move_action(self):
        """랜덤·벽 확률을 끄면 이동한다"""
        ai = SimpleAI(rng=StubRandom(1.0))
        game = GameState()
        game.move(1, 7, 4)

        action = ai.get_move(game)

        assert action.action_type == ActionType.MOVE
        assert game.move(2, action.row, action.col) is None

    def test_ai_wall_action(self):
        """상대가 더 가깝고 벽 확률을 통과하면 벽을 둔다"""
        ai = SimpleAI(difficulty="hard", rng=StubRandom(0.3))  # randomness 0.05 < 0.3 < 0.6
        game = GameState()
        game.seat(1).position = Position(2, 4)   # seat 1 이 목표에 훨씬 가깝다
        game.move(1, 2, 3)                        # seat 2 차례

        action = ai.get_move(game)

        assert action.action_type == ActionType.WALL
        assert game.place_wall(2, action.row, action.col, action.orientation.value) is None

    def test_ai_moves_toward_goal(self):
        """AI 가 목표 방향으로 이동"""
        ai = SimpleAI(rng=StubRandom(1.0))
        game = GameState()
        game.move(1, 7, 4)

        before = game.get_player_distance_to_goal(2)
        action = ai.get_move(game)
        game.move(2, action.row, action.col)

        assert game.get_player_distance_to_goal(2) == before - 1

    def test_ai_wins_when_possible(self):
        """한 칸 앞이 목표면 무조건 이동해 이긴다"""
        ai = SimpleAI(rng=StubRandom(1.0))
        game = GameState()
        game.move(1, 7, 4)
        game.seat(2).position = Position(7, 3)

        action = ai.get_move(game)

        assert action.action_type == ActionType.MOVE
        assert reaches_any(Position(action.row, action.col), game.seat(2).goals)

    def test_ai_no_walls_remaining(self):
        """벽이 없으면 이동만"""
        ai = SimpleAI(difficulty="hard", rng=random.Random(0))
        game = GameState()
        game.move(1, 7, 4)
        game.seat(2).walls_remaining = 0

        for _ in range(10):
            assert ai.get_move(game).action_type == ActionType.MOVE

    def test_ai_targets_leading_opponent(self):
        """방해 대상은 생존 상대 중 목표에 가장 가까운 좌석이다 (N인)"""
        game = GameState("trio", rng=random.Random(0))
        leader = game.seat(3)
        path = Pathfinder.find_shortest_path(leader.position, leader.goals, game.wall_manager)
        leader.position = path[-2]  # 목표 한 칸 앞. seat 2 는 시작점(거리 8)

        assert SimpleAI._leading_opponent(game).seat_no == 3

    def test_leading_opponent_skips_eliminated(self):
        game = GameState("trio", rng=random.Random(0))
        game.eliminate(3, "surrender")

        assert SimpleAI._leading_opponent(game).seat_no == 2


class TestAIConsistency:
    """AI 일관성 테스트"""

    def test_ai_consistency(self):
        """같은 시드면 같은 행동"""
        game = GameState()
        game.move(1, 7, 4)

        a1 = SimpleAI(difficulty="hard", rng=random.Random(42)).get_move(game)
        a2 = SimpleAI(difficulty="hard", rng=random.Random(42)).get_move(game)

        assert a1.to_dict() == a2.to_dict()

    def test_easy_more_random(self):
        assert SimpleAI(difficulty="easy").randomness > SimpleAI(difficulty="hard").randomness

    def test_hard_more_walls(self):
        assert SimpleAI(difficulty="hard").wall_probability > SimpleAI(difficulty="easy").wall_probability
