"""
Simple AI Module
휴리스틱 기반 AI 플레이어

전체 벽을 보고 판단한다 (Fog of War 무시). 온라인 AI 좌석으로 노출하기 전에
시야 제한을 다뤄야 한다 — docs/api/platform.md §6.
"""

import random
from typing import Optional

from ..core.game_state import GameState, Action, ActionType
from ..core.board import Position, reaches_any
from ..core.player import Player
from ..core.wall import Wall
from ..core.pathfinder import Pathfinder


class SimpleAI:
    """휴리스틱 기반 AI"""

    def __init__(self, difficulty: str = "normal", rng: Optional[random.Random] = None):
        """
        Args:
            difficulty: "easy", "normal", "hard"
            rng: 난수원 (테스트에서 시드 고정용)
        """
        self.difficulty = difficulty
        self.rng = rng or random.Random()

        # 난이도별 설정
        if difficulty == "easy":
            self.wall_probability = 0.1  # 벽 설치 확률
            self.randomness = 0.3  # 랜덤 행동 확률
        elif difficulty == "hard":
            self.wall_probability = 0.4
            self.randomness = 0.05
        else:  # normal
            self.wall_probability = 0.25
            self.randomness = 0.15

    def get_move(self, game_state: GameState) -> Optional[Action]:
        """
        현재 차례 좌석의 다음 행동 결정

        Returns:
            수행할 Action 또는 None
        """
        ai_player = game_state.current_player

        valid_moves = game_state.get_valid_pawn_moves()
        valid_walls = game_state.get_valid_wall_placements() if ai_player.has_walls() else []

        if not valid_moves and not valid_walls:
            return None

        # 랜덤 행동 (난이도에 따라)
        if self.rng.random() < self.randomness:
            return self._random_action(valid_moves, valid_walls)

        # 전략적 결정
        return self._strategic_action(game_state, valid_moves, valid_walls)

    @staticmethod
    def _leading_opponent(game_state: GameState) -> Optional[Player]:
        """생존 상대 중 목표에 가장 가까운 좌석 — 방해 대상"""
        me = game_state.current_seat_no
        opponents = [p for p in game_state.survivors if p.seat_no != me]
        if not opponents:
            return None
        return min(opponents, key=lambda p: game_state.get_player_distance_to_goal(p.seat_no))

    def _strategic_action(
        self,
        game_state: GameState,
        valid_moves: list[Position],
        valid_walls: list[Wall]
    ) -> Action:
        """전략적 행동 결정"""
        ai_player = game_state.current_player
        target = self._leading_opponent(game_state)
        wall_manager = game_state.wall_manager

        ai_distance = Pathfinder.get_shortest_distance(
            ai_player.position, ai_player.goals, wall_manager
        )

        # 1. 승리 직전이면 무조건 이동
        if ai_distance == 1:
            return self._move_to_goal(valid_moves, ai_player, wall_manager)

        if target is not None:
            target_distance = Pathfinder.get_shortest_distance(
                target.position, target.goals, wall_manager
            )

            # 2. 상대가 더 가까우면 벽으로 방해
            if (
                target_distance < ai_distance
                and valid_walls
                and self.rng.random() < self.wall_probability + 0.2
            ):
                wall = self._find_blocking_wall(game_state, target, valid_walls)
                if wall:
                    return self._wall_action(wall)

            # 3. 벽 설치 확률 체크
            if valid_walls and self.rng.random() < self.wall_probability:
                wall = self._find_blocking_wall(game_state, target, valid_walls)
                if wall:
                    return self._wall_action(wall)

        # 4. 기본: 목표 방향으로 이동
        best_move = self._find_best_move(valid_moves, ai_player, wall_manager)
        return Action(
            action_type=ActionType.MOVE,
            row=best_move.row,
            col=best_move.col
        )

    @staticmethod
    def _wall_action(wall: Wall) -> Action:
        return Action(
            action_type=ActionType.WALL,
            row=wall.row,
            col=wall.col,
            orientation=wall.orientation
        )

    def _move_to_goal(self, valid_moves: list[Position], ai_player: Player, wall_manager) -> Action:
        """목표 칸으로 이동"""
        for move in valid_moves:
            if reaches_any(move, ai_player.goals):
                return Action(
                    action_type=ActionType.MOVE,
                    row=move.row,
                    col=move.col
                )

        # 목표 칸 이동이 없으면 거리 기준 최선
        best_move = self._find_best_move(valid_moves, ai_player, wall_manager)
        return Action(
            action_type=ActionType.MOVE,
            row=best_move.row,
            col=best_move.col
        )

    def _find_best_move(
        self,
        valid_moves: list[Position],
        ai_player: Player,
        wall_manager
    ) -> Position:
        """최적의 이동 위치 찾기"""
        if not valid_moves:
            raise ValueError("No valid moves available")

        # 각 이동 후 목표까지 거리 계산
        move_scores = []
        for move in valid_moves:
            distance = Pathfinder.get_shortest_distance(move, ai_player.goals, wall_manager)
            # 거리가 짧을수록 좋음 (점수 높음)
            move_scores.append((move, -distance if distance >= 0 else -100))

        # 최고 점수 이동 선택 (동점이면 랜덤)
        max_score = max(score for _, score in move_scores)
        best_moves = [move for move, score in move_scores if score == max_score]

        return self.rng.choice(best_moves)

    def _find_blocking_wall(
        self,
        game_state: GameState,
        target: Player,
        valid_walls: list[Wall]
    ) -> Optional[Wall]:
        """방해 대상을 효과적으로 늦추는 벽 찾기"""
        wall_manager = game_state.wall_manager

        current_distance = Pathfinder.get_shortest_distance(
            target.position, target.goals, wall_manager
        )

        best_walls = []
        best_increase = 0

        # 샘플링 (전체 검사는 너무 느림)
        sample_size = min(50, len(valid_walls))
        sampled_walls = self.rng.sample(valid_walls, sample_size)

        for wall in sampled_walls:
            temp_manager = wall_manager.copy()
            temp_manager.add_wall(wall)

            new_distance = Pathfinder.get_shortest_distance(
                target.position, target.goals, temp_manager
            )

            if new_distance < 0:
                continue  # 경로 없음 (유효하지 않은 벽)

            increase = new_distance - current_distance

            if increase > best_increase:
                best_increase = increase
                best_walls = [wall]
            elif increase == best_increase and increase > 0:
                best_walls.append(wall)

        if best_walls:
            return self.rng.choice(best_walls)

        return None

    def _random_action(
        self,
        valid_moves: list[Position],
        valid_walls: list[Wall]
    ) -> Optional[Action]:
        """랜덤 행동"""
        actions = [
            Action(action_type=ActionType.MOVE, row=move.row, col=move.col)
            for move in valid_moves
        ]
        actions.extend(self._wall_action(wall) for wall in valid_walls[:20])  # 벽은 최대 20개만

        return self.rng.choice(actions) if actions else None
