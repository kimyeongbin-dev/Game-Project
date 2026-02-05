"""
Game Session Repository
게임 세션 데이터베이스 CRUD 작업
"""

from datetime import datetime
from typing import Optional
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from .models import GameSession, GameStatus, GameMode


class GameSessionRepository:
    """게임 세션 저장소"""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(
        self,
        game_id: str,
        player1_name: str,
        player2_name: str,
        game_mode: str,
        ai_difficulty: Optional[str],
        game_state: dict
    ) -> GameSession:
        """새 게임 세션 생성"""
        game_session = GameSession(
            game_id=game_id,
            player1_name=player1_name,
            player2_name=player2_name,
            game_mode=GameMode(game_mode),
            ai_difficulty=ai_difficulty if game_mode == "vs_ai" else None,
            game_state=game_state,
            game_history=[],
            status=GameStatus.IN_PROGRESS,
            current_turn=1,
            turn_count=0
        )
        self.session.add(game_session)
        await self.session.commit()
        await self.session.refresh(game_session)
        return game_session

    async def get_by_id(self, game_id: str) -> Optional[GameSession]:
        """게임 ID로 세션 조회"""
        result = await self.session.execute(
            select(GameSession).where(
                GameSession.game_id == game_id,
                GameSession.is_deleted == False
            )
        )
        return result.scalar_one_or_none()

    async def update_game_state(
        self,
        game_id: str,
        game_state: dict,
        action: Optional[dict] = None,
        status: Optional[str] = None,
        winner: Optional[int] = None
    ) -> Optional[GameSession]:
        """
        게임 상태 업데이트

        Args:
            game_id: 게임 ID
            game_state: 새 게임 상태
            action: 수행된 액션 (히스토리에 추가)
            status: 게임 상태 (in_progress, finished)
            winner: 승자 (1 또는 2)
        """
        game_session = await self.get_by_id(game_id)
        if not game_session:
            return None

        # 게임 상태 업데이트
        game_session.game_state = game_state
        game_session.current_turn = game_state.get("current_turn", 1)
        game_session.turn_count = game_state.get("turn_count", 0)
        game_session.updated_at = datetime.utcnow()

        # 상태 업데이트
        if status:
            game_session.status = GameStatus(status)

        # 승자 업데이트
        if winner is not None:
            game_session.winner = winner

        # 액션을 히스토리에 추가
        if action:
            history_entry = {
                "turn": game_session.turn_count,
                "player": action.get("player", game_session.current_turn),
                "action": action,
                "timestamp": datetime.utcnow().isoformat() + "Z"
            }
            # JSONB 배열에 추가 (기존 히스토리 복사 후 추가)
            current_history = game_session.game_history or []
            game_session.game_history = current_history + [history_entry]

        await self.session.commit()
        await self.session.refresh(game_session)
        return game_session

    async def get_active_sessions(self, limit: int = 50) -> list[GameSession]:
        """진행 중인 게임 세션 목록 조회"""
        result = await self.session.execute(
            select(GameSession)
            .where(
                GameSession.status == GameStatus.IN_PROGRESS,
                GameSession.is_deleted == False
            )
            .order_by(GameSession.updated_at.desc())
            .limit(limit)
        )
        return list(result.scalars().all())

    async def get_recent_sessions(
        self,
        limit: int = 20,
        include_finished: bool = True
    ) -> list[GameSession]:
        """최근 게임 세션 목록 조회"""
        query = select(GameSession).where(GameSession.is_deleted == False)

        if not include_finished:
            query = query.where(GameSession.status == GameStatus.IN_PROGRESS)

        query = query.order_by(GameSession.updated_at.desc()).limit(limit)
        result = await self.session.execute(query)
        return list(result.scalars().all())

    async def soft_delete(self, game_id: str) -> bool:
        """게임 세션 소프트 삭제"""
        game_session = await self.get_by_id(game_id)
        if not game_session:
            return False

        game_session.is_deleted = True
        game_session.updated_at = datetime.utcnow()
        await self.session.commit()
        return True

    async def mark_abandoned(self, game_id: str) -> bool:
        """게임을 포기 상태로 변경"""
        game_session = await self.get_by_id(game_id)
        if not game_session:
            return False

        game_session.status = GameStatus.ABANDONED
        game_session.updated_at = datetime.utcnow()
        await self.session.commit()
        return True

    async def get_game_history(self, game_id: str) -> Optional[list]:
        """게임 히스토리 조회 (리플레이용)"""
        game_session = await self.get_by_id(game_id)
        if not game_session:
            return None
        return game_session.game_history
