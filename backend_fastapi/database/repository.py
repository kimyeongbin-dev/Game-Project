"""
Game Session Repository
게임 세션 데이터베이스 CRUD 작업
"""

from datetime import datetime
from typing import Optional
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from .models import GameSession, GameStatus, GameMode, GameMove, ActionType


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

    async def abandon_game(self, game_id: str) -> bool:
        """게임 포기 (기록은 보존, 활성 목록에서만 제외)"""
        game_session = await self.get_by_id(game_id)
        if not game_session:
            return False

        game_session.status = GameStatus.ABANDONED
        game_session.updated_at = datetime.utcnow()
        await self.session.commit()
        return True

    async def hard_delete(self, game_id: str) -> bool:
        """게임 완전 삭제 (기록도 숨김)"""
        game_session = await self.get_by_id(game_id)
        if not game_session:
            return False

        game_session.status = GameStatus.ABANDONED
        game_session.is_deleted = True
        game_session.updated_at = datetime.utcnow()
        await self.session.commit()
        return True

    async def get_game_history(self, game_id: str) -> Optional[list]:
        """게임 히스토리 조회 (리플레이용) - 기존 JSONB 방식"""
        game_session = await self.get_by_id(game_id)
        if not game_session:
            return None
        return game_session.game_history

    # ===== GameMove 관련 메서드 (리플레이 시스템) =====

    async def add_move(
        self,
        game_id: str,
        step_no: int,
        player: int,
        action_type: str,
        row: int,
        col: int,
        orientation: Optional[str],
        game_state_snapshot: dict
    ) -> GameMove:
        """새로운 수 기록 추가"""
        move = GameMove(
            game_id=game_id,
            step_no=step_no,
            player=player,
            action_type=ActionType(action_type),
            row=row,
            col=col,
            orientation=orientation,
            game_state_snapshot=game_state_snapshot
        )
        self.session.add(move)
        await self.session.commit()
        await self.session.refresh(move)
        return move

    async def get_moves(self, game_id: str) -> list[GameMove]:
        """게임의 모든 수 조회 (step_no 순서)"""
        result = await self.session.execute(
            select(GameMove)
            .where(GameMove.game_id == game_id)
            .order_by(GameMove.step_no)
        )
        return list(result.scalars().all())

    async def get_move_at_step(self, game_id: str, step_no: int) -> Optional[GameMove]:
        """특정 스텝의 수 조회"""
        result = await self.session.execute(
            select(GameMove)
            .where(GameMove.game_id == game_id, GameMove.step_no == step_no)
        )
        return result.scalar_one_or_none()

    async def get_state_at_step(self, game_id: str, step_no: int) -> Optional[dict]:
        """특정 스텝에서의 게임 상태 스냅샷 조회"""
        if step_no < 0:
            # step 0 이전은 초기 상태 (게임 세션에서 조회)
            game_session = await self.get_by_id(game_id)
            if not game_session:
                return None
            # 초기 상태 반환 (첫 번째 move가 있으면 그 전 상태, 없으면 현재 상태)
            moves = await self.get_moves(game_id)
            if not moves:
                return game_session.game_state
            # 초기 상태는 별도로 저장하지 않았으므로 None 반환
            return None

        move = await self.get_move_at_step(game_id, step_no)
        if not move:
            return None
        return move.game_state_snapshot

    async def get_total_moves(self, game_id: str) -> int:
        """게임의 총 수 개수"""
        result = await self.session.execute(
            select(GameMove)
            .where(GameMove.game_id == game_id)
        )
        return len(list(result.scalars().all()))

    async def delete_moves_after(self, game_id: str, step_no: int) -> int:
        """특정 스텝 이후의 수 삭제 (되돌리기용)"""
        result = await self.session.execute(
            select(GameMove)
            .where(GameMove.game_id == game_id, GameMove.step_no > step_no)
        )
        moves = list(result.scalars().all())
        count = len(moves)
        for move in moves:
            await self.session.delete(move)
        await self.session.commit()
        return count
