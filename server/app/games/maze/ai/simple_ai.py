"""
Simple AI Module
휴리스틱 기반 AI 플레이어
"""

import random
from typing import Optional

from ..core.game_state import GameState, Action, ActionType
from ..core.board import Board, Position
from ..core.wall import Wall, Orientation
from ..core.move_validator import MoveValidator
from ..core.pathfinder import Pathfinder


class SimpleAI:
    """휴리스틱 기반 AI"""

    def __init__(self, difficulty: str = "normal"):
        """
        Args:
            difficulty: "easy", "normal", "hard"
        """
        self.difficulty = difficulty

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
        AI의 다음 행동 결정

        Args:
            game_state: 현재 게임 상태

        Returns:
            수행할 Action 또는 None
        """
        ai_player = game_state.current_player
        opponent = game_state.opponent_player

        # 유효한 이동 목록 가져오기
        valid_moves = game_state.get_valid_pawn_moves()
        valid_walls = game_state.get_valid_wall_placements() if ai_player.has_walls() else []

        if not valid_moves and not valid_walls:
            return None

        # 랜덤 행동 (난이도에 따라)
        if random.random() < self.randomness:
            return self._random_action(valid_moves, valid_walls)

        # 전략적 결정
        return self._strategic_action(game_state, valid_moves, valid_walls)

    def _strategic_action(
        self,
        game_state: GameState,
        valid_moves: list[Position],
        valid_walls: list[Wall]
    ) -> Action:
        """전략적 행동 결정"""
        ai_player = game_state.current_player
        opponent = game_state.opponent_player
        wall_manager = game_state.wall_manager

        # 각 플레이어의 목표까지 거리 계산
        ai_distance = Pathfinder.get_shortest_distance(
            ai_player.position, ai_player.goal_row, wall_manager
        )
        opponent_distance = Pathfinder.get_shortest_distance(
            opponent.position, opponent.goal_row, wall_manager
        )

        # 1. 승리 직전이면 무조건 이동
        if ai_distance == 1:
            return self._move_to_goal(valid_moves, ai_player.goal_row)

        # 2. 상대가 더 가까우면 벽으로 방해
        if (
            opponent_distance < ai_distance
            and valid_walls
            and random.random() < self.wall_probability + 0.2
        ):
            wall = self._find_blocking_wall(game_state, valid_walls)
            if wall:
                return Action(
                    action_type=ActionType.WALL,
                    row=wall.row,
                    col=wall.col,
                    orientation=wall.orientation
                )

        # 3. 벽 설치 확률 체크
        if valid_walls and random.random() < self.wall_probability:
            wall = self._find_blocking_wall(game_state, valid_walls)
            if wall:
                return Action(
                    action_type=ActionType.WALL,
                    row=wall.row,
                    col=wall.col,
                    orientation=wall.orientation
                )

        # 4. 기본: 목표 방향으로 이동
        best_move = self._find_best_move(valid_moves, ai_player.goal_row, wall_manager)
        return Action(
            action_type=ActionType.MOVE,
            row=best_move.row,
            col=best_move.col
        )

    def _move_to_goal(self, valid_moves: list[Position], goal_row: int) -> Action:
        """목표 행으로 이동"""
        for move in valid_moves:
            if move.row == goal_row:
                return Action(
                    action_type=ActionType.MOVE,
                    row=move.row,
                    col=move.col
                )

        # 목표 행 이동이 없으면 가장 가까운 이동
        best_move = min(valid_moves, key=lambda m: abs(m.row - goal_row))
        return Action(
            action_type=ActionType.MOVE,
            row=best_move.row,
            col=best_move.col
        )

    def _find_best_move(
        self,
        valid_moves: list[Position],
        goal_row: int,
        wall_manager
    ) -> Position:
        """최적의 이동 위치 찾기"""
        if not valid_moves:
            raise ValueError("No valid moves available")

        # 각 이동 후 목표까지 거리 계산
        move_scores = []
        for move in valid_moves:
            distance = Pathfinder.get_shortest_distance(move, goal_row, wall_manager)
            # 거리가 짧을수록 좋음 (점수 높음)
            move_scores.append((move, -distance if distance >= 0 else -100))

        # 최고 점수 이동 선택 (동점이면 랜덤)
        max_score = max(score for _, score in move_scores)
        best_moves = [move for move, score in move_scores if score == max_score]

        return random.choice(best_moves)

    def _find_blocking_wall(
        self,
        game_state: GameState,
        valid_walls: list[Wall]
    ) -> Optional[Wall]:
        """상대방을 효과적으로 방해하는 벽 찾기"""
        opponent = game_state.opponent_player
        wall_manager = game_state.wall_manager

        # 현재 상대방 거리
        current_distance = Pathfinder.get_shortest_distance(
            opponent.position, opponent.goal_row, wall_manager
        )

        # 벽 효과 평가
        best_walls = []
        best_increase = 0

        # 샘플링 (전체 검사는 너무 느림)
        sample_size = min(50, len(valid_walls))
        sampled_walls = random.sample(valid_walls, sample_size)

        for wall in sampled_walls:
            # 임시로 벽 설치
            temp_manager = wall_manager.copy()
            temp_manager.add_wall(wall)

            new_distance = Pathfinder.get_shortest_distance(
                opponent.position, opponent.goal_row, temp_manager
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
            return random.choice(best_walls)

        return None

    def _random_action(
        self,
        valid_moves: list[Position],
        valid_walls: list[Wall]
    ) -> Action:
        """랜덤 행동"""
        # 이동과 벽 설치 중 선택
        actions = []

        for move in valid_moves:
            actions.append(Action(
                action_type=ActionType.MOVE,
                row=move.row,
                col=move.col
            ))

        for wall in valid_walls[:20]:  # 벽은 최대 20개만
            actions.append(Action(
                action_type=ActionType.WALL,
                row=wall.row,
                col=wall.col,
                orientation=wall.orientation
            ))

        return random.choice(actions) if actions else None
