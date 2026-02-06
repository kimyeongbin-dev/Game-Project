"""
Quoridor Service
게임 비즈니스 로직 (DB 연동)
"""

import sys
import logging
from pathlib import Path
from typing import Optional
from datetime import datetime, timedelta

# 로깅 설정
logger = logging.getLogger(__name__)

# games 패키지 경로 추가
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from games.__init__ import *

# 게임 로직 임포트
from games import GameState, Wall
from games.game_Quoridor.core.board import Position
from games.game_Quoridor.core.wall import Orientation
from games.game_Quoridor.ai.simple_ai import SimpleAI

# DB 관련 임포트
from database import get_session_factory, is_db_available
from database.repository import GameSessionRepository


class QuoridorService:
    """쿼리도 게임 서비스 (DB 연동)"""

    # 캐시 설정
    CACHE_TTL_MINUTES = 60  # 캐시 유지 시간 (분)
    MAX_CACHED_GAMES = 100  # 최대 캐시 게임 수

    def __init__(self):
        # 메모리 기반 게임 저장소 (캐시 역할)
        self._games: dict[str, GameState] = {}
        self._ai_instances: dict[str, SimpleAI] = {}
        self._ai_difficulties: dict[str, str] = {}
        # 게임 마지막 액세스 시간 추적
        self._last_accessed: dict[str, datetime] = {}

    def _update_access_time(self, game_id: str) -> None:
        """게임 액세스 시간 업데이트"""
        self._last_accessed[game_id] = datetime.utcnow()

    def _cleanup_stale_games(self) -> int:
        """오래된 게임 캐시 정리 (TTL 기반)"""
        now = datetime.utcnow()
        ttl = timedelta(minutes=self.CACHE_TTL_MINUTES)
        stale_ids = [
            game_id for game_id, last_access in self._last_accessed.items()
            if now - last_access > ttl
        ]

        for game_id in stale_ids:
            self._remove_from_cache(game_id)

        if stale_ids:
            logger.info(f"Cleaned up {len(stale_ids)} stale games from cache")

        return len(stale_ids)

    def _enforce_cache_limit(self) -> int:
        """캐시 크기 제한 적용 (LRU 방식)"""
        if len(self._games) <= self.MAX_CACHED_GAMES:
            return 0

        # 액세스 시간 기준 정렬하여 오래된 것 제거
        sorted_games = sorted(
            self._last_accessed.items(),
            key=lambda x: x[1]
        )

        to_remove = len(self._games) - self.MAX_CACHED_GAMES
        removed = 0

        for game_id, _ in sorted_games[:to_remove]:
            self._remove_from_cache(game_id)
            removed += 1

        if removed:
            logger.info(f"Removed {removed} games from cache (limit enforcement)")

        return removed

    def _remove_from_cache(self, game_id: str) -> None:
        """게임을 캐시에서 제거"""
        self._games.pop(game_id, None)
        self._ai_instances.pop(game_id, None)
        self._ai_difficulties.pop(game_id, None)
        self._last_accessed.pop(game_id, None)

    async def cleanup_cache(self) -> dict:
        """캐시 정리 수행 (수동 호출 또는 스케줄러용)"""
        stale_removed = self._cleanup_stale_games()
        limit_removed = self._enforce_cache_limit()
        return {
            "stale_removed": stale_removed,
            "limit_removed": limit_removed,
            "current_cache_size": len(self._games)
        }

    async def _save_to_db(
        self,
        game: GameState,
        action: Optional[dict] = None,
        is_new: bool = False,
        ai_difficulty: Optional[str] = None
    ) -> None:
        """게임 상태를 DB에 저장 (단일 트랜잭션)"""
        if not is_db_available():
            return  # DB 없으면 스킵

        session_factory = get_session_factory()
        if session_factory is None:
            return

        try:
            async with session_factory() as session:
                repo = GameSessionRepository(session)

                if is_new:
                    # 새 게임 생성
                    await repo.create(
                        game_id=game.game_id,
                        player1_name=game.player1.name,
                        player2_name=game.player2.name,
                        game_mode=game.game_mode.value,
                        ai_difficulty=ai_difficulty,
                        game_state=game.to_dict()
                    )
                    # 초기 상태를 step -1로 저장 (리플레이 시작점)
                    await repo.add_move(
                        game_id=game.game_id,
                        step_no=-1,
                        player=0,  # 초기 상태는 플레이어 0
                        action_type="move",  # 더미 타입
                        row=0,
                        col=0,
                        orientation=None,
                        game_state_snapshot=game.to_dict()
                    )
                else:
                    # 기존 게임 업데이트 + 액션 저장 (단일 트랜잭션)
                    status = game.status.value
                    winner = game.winner

                    # GameMove 먼저 추가 (같은 세션 내)
                    if action:
                        step_no = game.turn_count
                        await repo.add_move_no_commit(
                            game_id=game.game_id,
                            step_no=step_no,
                            player=action.get("player", 1),
                            action_type=action.get("type", "move"),
                            row=action.get("row", 0),
                            col=action.get("col", 0),
                            orientation=action.get("orientation"),
                            game_state_snapshot=game.to_dict()
                        )

                    # 게임 상태 업데이트 (커밋은 여기서 한 번만)
                    await repo.update_game_state(
                        game_id=game.game_id,
                        game_state=game.to_dict(),
                        status=status,
                        winner=winner
                    )
        except Exception as e:
            # DB 저장 실패해도 메모리 게임은 계속 진행
            logger.warning(f"Failed to save game to DB: {e}")

    async def _load_from_db(self, game_id: str) -> Optional[GameState]:
        """DB에서 게임 상태 복구"""
        if not is_db_available():
            return None  # DB 없으면 None 반환

        try:
            async with get_session_factory()() as session:
                repo = GameSessionRepository(session)
                game_session = await repo.get_by_id(game_id)

                if not game_session:
                    return None

                # GameState 객체로 복원
                game = GameState.from_dict(game_session.game_state)

                # AI 인스턴스 복원 (vs_ai 모드일 때)
                if game_session.game_mode.value == "vs_ai":
                    difficulty = game_session.ai_difficulty or "normal"
                    self._ai_instances[game_id] = SimpleAI(difficulty=difficulty)
                    self._ai_difficulties[game_id] = difficulty

                return game
        except Exception as e:
            logger.warning(f"Failed to load game from DB: {e}")
            return None

    async def create_game(
        self,
        player1_name: str = "Player 1",
        player2_name: str = "Player 2",
        ai_difficulty: str = "normal",
        game_mode: str = "vs_ai"
    ) -> GameState:
        """새 게임 생성"""
        # 캐시 정리 수행 (새 게임 생성 시)
        self._cleanup_stale_games()
        self._enforce_cache_limit()

        # 로컬 2인 모드일 경우 player2_name 사용, AI 모드는 "AI"
        p2_name = player2_name if game_mode == "local_2p" else "AI"
        game = GameState(
            player1_name=player1_name,
            player2_name=p2_name,
            game_mode=game_mode
        )
        self._games[game.game_id] = game
        self._update_access_time(game.game_id)

        # AI 모드일 때만 AI 인스턴스 생성
        if game_mode == "vs_ai":
            self._ai_instances[game.game_id] = SimpleAI(difficulty=ai_difficulty)
            self._ai_difficulties[game.game_id] = ai_difficulty

        # DB에 저장
        await self._save_to_db(game, is_new=True, ai_difficulty=ai_difficulty)

        return game

    async def get_game(self, game_id: str) -> Optional[GameState]:
        """게임 조회 (메모리 -> DB 순으로 조회)"""
        # 메모리에서 먼저 조회
        game = self._games.get(game_id)
        if game:
            self._update_access_time(game_id)
            return game

        # 메모리에 없으면 DB에서 복구 시도
        game = await self._load_from_db(game_id)
        if game:
            self._games[game_id] = game
            self._update_access_time(game_id)
            return game

        return None

    async def move_pawn(self, game_id: str, row: int, col: int) -> tuple[bool, str, Optional[GameState]]:
        """
        폰 이동

        Returns:
            (성공 여부, 메시지, 게임 상태)
        """
        game = await self.get_game(game_id)
        if not game:
            return False, "Game not found", None

        current_player = game.current_turn
        success, message = game.move_pawn(row, col)

        if success:
            # 액션 기록
            action = {
                "type": "move",
                "player": current_player,
                "row": row,
                "col": col
            }
            # DB에 저장
            await self._save_to_db(game, action=action)

        return success, message, game if success else None

    async def place_wall(
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
        game = await self.get_game(game_id)
        if not game:
            return False, "Game not found", None

        current_player = game.current_turn
        success, message = game.place_wall(row, col, orientation)

        if success:
            # 액션 기록
            action = {
                "type": "wall",
                "player": current_player,
                "row": row,
                "col": col,
                "orientation": orientation
            }
            # DB에 저장
            await self._save_to_db(game, action=action)

        return success, message, game if success else None

    async def ai_move(self, game_id: str) -> tuple[bool, str, Optional[dict], Optional[GameState]]:
        """
        AI 턴 수행

        Returns:
            (성공 여부, 메시지, 액션 정보, 게임 상태)
        """
        game = await self.get_game(game_id)
        if not game:
            return False, "Game not found", None, None

        if game.current_turn != 2:
            return False, "Not AI's turn", None, None

        if game.status.value in ("player1_win", "player2_win"):
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

        if success:
            # 액션에 플레이어 정보 추가
            action_with_player = {
                **action_info,
                "player": 2
            }
            # DB에 저장
            await self._save_to_db(game, action=action_with_player)

        return success, message, action_info, game if success else None

    async def get_valid_moves(self, game_id: str) -> Optional[dict]:
        """유효한 이동 목록 조회"""
        game = await self.get_game(game_id)
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

    async def abandon_game(self, game_id: str) -> bool:
        """게임 포기 (기록은 보존, 활성 목록에서만 제외)"""
        # 메모리에서 삭제
        self._remove_from_cache(game_id)

        # DB에서 포기 처리
        if not is_db_available():
            return True

        try:
            async with get_session_factory()() as session:
                repo = GameSessionRepository(session)
                return await repo.abandon_game(game_id)
        except Exception as e:
            logger.warning(f"Failed to abandon game in DB: {e}")
            return True

    async def delete_game(self, game_id: str) -> bool:
        """게임 완전 삭제 (기록도 숨김)"""
        # 메모리에서 삭제
        self._remove_from_cache(game_id)

        # DB에서 완전 삭제
        if not is_db_available():
            return True

        try:
            async with get_session_factory()() as session:
                repo = GameSessionRepository(session)
                return await repo.hard_delete(game_id)
        except Exception as e:
            logger.warning(f"Failed to delete game from DB: {e}")
            return True

    async def recover_game(self, game_id: str) -> Optional[GameState]:
        """
        DB에서 게임 복구 (서버 재시작 후 세션 복구용)

        Returns:
            복구된 GameState 또는 None
        """
        # 이미 메모리에 있으면 그대로 반환
        if game_id in self._games:
            return self._games[game_id]

        # DB에서 복구
        game = await self._load_from_db(game_id)
        if game:
            self._games[game_id] = game
            return game

        return None

    async def get_active_sessions(self, limit: int = 50) -> list[dict]:
        """진행 중인 게임 세션 목록"""
        if not is_db_available():
            # DB 없으면 메모리에서 진행 중인 게임 반환
            return [
                {
                    "game_id": game.game_id,
                    "player1_name": game.player1.name,
                    "player2_name": game.player2.name,
                    "game_mode": game.game_mode.value,
                    "current_turn": game.current_turn,
                    "turn_count": game.turn_count,
                    "created_at": game.created_at.isoformat() + "Z",
                    "updated_at": game.updated_at.isoformat() + "Z"
                }
                for game in list(self._games.values())[:limit]
                if game.status.value == "in_progress"
            ]

        try:
            async with get_session_factory()() as session:
                repo = GameSessionRepository(session)
                sessions = await repo.get_active_sessions(limit=limit)
                return [
                    {
                        "game_id": s.game_id,
                        "player1_name": s.player1_name,
                        "player2_name": s.player2_name,
                        "game_mode": s.game_mode.value,
                        "current_turn": s.current_turn,
                        "turn_count": s.turn_count,
                        "created_at": s.created_at.isoformat() + "Z",
                        "updated_at": s.updated_at.isoformat() + "Z"
                    }
                    for s in sessions
                ]
        except Exception as e:
            logger.warning(f"Failed to get active sessions: {e}")
            return []

    async def get_game_history(self, game_id: str) -> Optional[list]:
        """게임 히스토리 조회 (리플레이용) - 기존 JSONB 방식"""
        if not is_db_available():
            return [] if game_id in self._games else None

        try:
            async with get_session_factory()() as session:
                repo = GameSessionRepository(session)
                return await repo.get_game_history(game_id)
        except Exception as e:
            logger.warning(f"Failed to get game history: {e}")
            return None

    # ===== 리플레이 시스템 메서드 =====

    async def get_replay_moves(self, game_id: str) -> Optional[list[dict]]:
        """리플레이용 수 목록 조회 (GameMove 테이블)"""
        if not is_db_available():
            return None

        try:
            async with get_session_factory()() as session:
                repo = GameSessionRepository(session)
                moves = await repo.get_moves(game_id)
                return [move.to_dict() for move in moves]
        except Exception as e:
            logger.warning(f"Failed to get replay moves: {e}")
            return None

    async def get_state_at_step(self, game_id: str, step_no: int) -> Optional[dict]:
        """특정 스텝에서의 게임 상태 조회 (step -1 = 초기 상태)"""
        if not is_db_available():
            return None

        session_factory = get_session_factory()
        if session_factory is None:
            return None

        try:
            async with session_factory() as session:
                repo = GameSessionRepository(session)
                return await repo.get_state_at_step(game_id, step_no)
        except Exception as e:
            logger.warning(f"Failed to get state at step: {e}")
            return None

    async def get_total_moves(self, game_id: str) -> int:
        """게임의 총 수 개수"""
        if not is_db_available():
            return 0

        try:
            async with get_session_factory()() as session:
                repo = GameSessionRepository(session)
                return await repo.get_total_moves(game_id)
        except Exception as e:
            logger.warning(f"Failed to get total moves: {e}")
            return 0


# 싱글톤 인스턴스
quoridor_service = QuoridorService()
