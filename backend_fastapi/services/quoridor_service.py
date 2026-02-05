"""
Quoridor Service
게임 비즈니스 로직
"""

import sys
from pathlib import Path
from typing import Optional

# games 패키지 경로 추가
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from games.__init__ import *

# 게임 로직 임포트
from games import GameState, Wall
from games.game_Quoridor.core.board import Position
from games.game_Quoridor.core.wall import Orientation
from games.game_Quoridor.ai.simple_ai import SimpleAI


class QuoridorService:
    """쿼리도 게임 서비스"""

    def __init__(self):
        # 메모리 기반 게임 저장소 (프로덕션에서는 DB 사용)
        self._games: dict[str, GameState] = {}
        self._ai_instances: dict[str, SimpleAI] = {}

    def create_game(
        self,
        player_name: str = "Player",
        player2_name: str = "Player 2",
        ai_difficulty: str = "normal",
        game_mode: str = "vs_ai"
    ) -> GameState:
        """새 게임 생성"""
        # 로컬 2인 모드일 경우 player2_name 사용, AI 모드는 "AI"
        p2_name = player2_name if game_mode == "local_2p" else "AI"
        game = GameState(
            player1_name=player_name,
            player2_name=p2_name,
            game_mode=game_mode
        )
        self._games[game.game_id] = game

        # AI 모드일 때만 AI 인스턴스 생성
        if game_mode == "vs_ai":
            self._ai_instances[game.game_id] = SimpleAI(difficulty=ai_difficulty)

        return game

    def get_game(self, game_id: str) -> Optional[GameState]:
        """게임 조회"""
        return self._games.get(game_id)

    def move_pawn(self, game_id: str, row: int, col: int) -> tuple[bool, str, Optional[GameState]]:
        """
        폰 이동

        Returns:
            (성공 여부, 메시지, 게임 상태)
        """
        game = self.get_game(game_id)
        if not game:
            return False, "Game not found", None

        success, message = game.move_pawn(row, col)
        return success, message, game if success else None

    def place_wall(
        self,
        game_id: str,
        row: int,
        col: int,
        orientation: str
    ) -> tuple[bool, str, Optional[GameState]]:
        """
        벽 설치

        Returns:
            (성공 여부, 메시지, 게임 상태)
        """
        game = self.get_game(game_id)
        if not game:
            return False, "Game not found", None

        success, message = game.place_wall(row, col, orientation)
        return success, message, game if success else None

    def ai_move(self, game_id: str) -> tuple[bool, str, Optional[dict], Optional[GameState]]:
        """
        AI 턴 수행

        Returns:
            (성공 여부, 메시지, 액션 정보, 게임 상태)
        """
        game = self.get_game(game_id)
        if not game:
            return False, "Game not found", None, None

        if game.current_turn != 2:
            return False, "Not AI's turn", None, None

        if game.status.value == "finished":
            return False, "Game is already finished", None, None

        ai = self._ai_instances.get(game_id)
        if not ai:
            ai = SimpleAI()
            self._ai_instances[game_id] = ai

        action = ai.get_move(game)
        if not action:
            return False, "AI could not find a valid move", None, None

        action_info = action.to_dict()

        if action.action_type.value == "move":
            success, message = game.move_pawn(action.row, action.col)
        else:
            success, message = game.place_wall(
                action.row,
                action.col,
                action.orientation.value if action.orientation else "horizontal"
            )

        return success, message, action_info, game if success else None

    def get_valid_moves(self, game_id: str) -> Optional[dict]:
        """유효한 이동 목록 조회"""
        game = self.get_game(game_id)
        if not game:
            return None

        pawn_moves = game.get_valid_pawn_moves()
        wall_placements = game.get_valid_wall_placements()

        return {
            "valid_pawn_moves": [
                {"row": pos.row, "col": pos.col}
                for pos in pawn_moves
            ],
            "valid_wall_placements": [
                wall.to_dict()
                for wall in wall_placements
            ],
            "walls_remaining": game.current_player.walls_remaining
        }

    def delete_game(self, game_id: str) -> bool:
        """게임 삭제"""
        if game_id in self._games:
            del self._games[game_id]
            if game_id in self._ai_instances:
                del self._ai_instances[game_id]
            return True
        return False


# 싱글톤 인스턴스
quoridor_service = QuoridorService()
