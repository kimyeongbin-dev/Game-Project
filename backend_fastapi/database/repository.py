"""
Game Session Repository
게임 세션 데이터베이스 CRUD 작업
"""

from datetime import datetime, date
from typing import Optional
import secrets
import re
import bcrypt
from sqlalchemy import select, update, func, delete, and_, or_
from sqlalchemy.ext.asyncio import AsyncSession

from .models import (
    GameSession, GameStatus, GameMode, GameMove, ActionType,
    User, DailyChampion, MatchQueue, MatchQueueStatus, GameRoom, RoomStatus
)


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
        status: Optional[str] = None,
        winner: Optional[int] = None
    ) -> Optional[GameSession]:
        """
        게임 상태 업데이트

        Args:
            game_id: 게임 ID
            game_state: 새 게임 상태
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

        # NOTE: game_history JSONB는 더 이상 업데이트하지 않음
        # 모든 히스토리는 GameMove 테이블에서 관리

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
        """새로운 수 기록 추가 (커밋 포함)"""
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

    async def add_move_no_commit(
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
        """새로운 수 기록 추가 (커밋 없음 - 트랜잭션 원자성용)"""
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
        # step -1은 초기 상태 (GameMove 테이블에 저장됨)
        move = await self.get_move_at_step(game_id, step_no)
        if not move:
            return None
        return move.game_state_snapshot

    async def get_total_moves(self, game_id: str) -> int:
        """게임의 총 수 개수 (초기 상태 step -1 제외)"""
        result = await self.session.execute(
            select(func.count(GameMove.id))
            .where(GameMove.game_id == game_id)
            .where(GameMove.step_no >= 0)  # 초기 상태 제외
        )
        return result.scalar() or 0

    async def delete_moves_after(self, game_id: str, step_no: int) -> int:
        """특정 스텝 이후의 수 삭제 (되돌리기용)"""
        # COUNT로 먼저 개수 확인
        count_result = await self.session.execute(
            select(func.count(GameMove.id))
            .where(GameMove.game_id == game_id)
            .where(GameMove.step_no > step_no)
        )
        count = count_result.scalar() or 0

        # DELETE 문으로 일괄 삭제
        if count > 0:
            await self.session.execute(
                delete(GameMove)
                .where(GameMove.game_id == game_id)
                .where(GameMove.step_no > step_no)
            )
            await self.session.commit()

        return count


# ===== 유저 관련 Repository =====

class UserRepository:
    """유저 저장소"""

    # 닉네임 규칙: 2-12자, 영문/숫자/한글
    NICKNAME_PATTERN = re.compile(r'^[a-zA-Z0-9가-힣]{2,12}$')

    def __init__(self, session: AsyncSession):
        self.session = session

    def _generate_token(self) -> str:
        """64자 세션 토큰 생성"""
        return secrets.token_hex(32)

    def _hash_password(self, password: str) -> str:
        """비밀번호 해시"""
        return bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')

    def _verify_password(self, password: str, hashed: str) -> bool:
        """비밀번호 검증"""
        return bcrypt.checkpw(password.encode('utf-8'), hashed.encode('utf-8'))

    def validate_nickname(self, nickname: str) -> tuple[bool, str]:
        """닉네임 유효성 검사"""
        if not nickname:
            return False, "닉네임을 입력해주세요"
        if len(nickname) < 2:
            return False, "닉네임은 2자 이상이어야 합니다"
        if len(nickname) > 12:
            return False, "닉네임은 12자 이하여야 합니다"
        if not self.NICKNAME_PATTERN.match(nickname):
            return False, "닉네임은 영문, 숫자, 한글만 사용 가능합니다"
        return True, ""

    def validate_password(self, password: str) -> tuple[bool, str]:
        """비밀번호 유효성 검사"""
        if not password:
            return False, "비밀번호를 입력해주세요"
        if len(password) < 4:
            return False, "비밀번호는 4자 이상이어야 합니다"
        if len(password) > 50:
            return False, "비밀번호는 50자 이하여야 합니다"
        return True, ""

    async def create(self, nickname: str, password: str) -> tuple[Optional[User], str]:
        """유저 생성 (닉네임 중복 체크 + 비밀번호 해시)"""
        # 닉네임 유효성 검사
        is_valid, error_msg = self.validate_nickname(nickname)
        if not is_valid:
            return None, error_msg

        # 비밀번호 유효성 검사
        is_valid, error_msg = self.validate_password(password)
        if not is_valid:
            return None, error_msg

        # 중복 체크
        existing = await self.get_by_nickname(nickname)
        if existing:
            return None, "이미 사용 중인 닉네임입니다"

        # 유저 생성
        user = User(
            nickname=nickname,
            password_hash=self._hash_password(password),
            session_token=self._generate_token(),
            score=0,
            wins=0,
            losses=0,
            is_online=True,
            last_active_at=datetime.utcnow()
        )
        self.session.add(user)
        await self.session.commit()
        await self.session.refresh(user)
        return user, ""

    async def get_by_id(self, user_id: int) -> Optional[User]:
        """ID로 유저 조회"""
        result = await self.session.execute(
            select(User).where(User.id == user_id)
        )
        return result.scalar_one_or_none()

    async def get_by_nickname(self, nickname: str) -> Optional[User]:
        """닉네임으로 유저 조회"""
        result = await self.session.execute(
            select(User).where(User.nickname == nickname)
        )
        return result.scalar_one_or_none()

    async def get_by_token(self, token: str) -> Optional[User]:
        """세션 토큰으로 유저 조회"""
        result = await self.session.execute(
            select(User).where(User.session_token == token)
        )
        return result.scalar_one_or_none()

    async def login(self, nickname: str, password: str) -> tuple[Optional[User], str]:
        """로그인 (비밀번호 검증 + 새 토큰 발급)"""
        user = await self.get_by_nickname(nickname)
        if not user:
            return None, "닉네임 또는 비밀번호가 올바르지 않습니다"

        # 비밀번호 검증
        if not self._verify_password(password, user.password_hash):
            return None, "닉네임 또는 비밀번호가 올바르지 않습니다"

        # 새 토큰 발급 및 온라인 상태 업데이트
        user.session_token = self._generate_token()
        user.is_online = True
        user.last_active_at = datetime.utcnow()
        await self.session.commit()
        await self.session.refresh(user)
        return user, ""

    async def logout(self, user_id: int) -> bool:
        """로그아웃"""
        user = await self.get_by_id(user_id)
        if not user:
            return False

        user.is_online = False
        user.current_game_id = None
        await self.session.commit()
        return True

    async def update_heartbeat(self, user_id: int) -> bool:
        """접속 상태 갱신 (heartbeat)"""
        user = await self.get_by_id(user_id)
        if not user:
            return False

        user.is_online = True
        user.last_active_at = datetime.utcnow()
        await self.session.commit()
        return True

    async def set_current_game(self, user_id: int, game_id: Optional[str]) -> bool:
        """현재 게임 ID 설정"""
        user = await self.get_by_id(user_id)
        if not user:
            return False

        user.current_game_id = game_id
        user.last_active_at = datetime.utcnow()
        await self.session.commit()
        return True

    async def update_score(
        self,
        user_id: int,
        score_change: float,
        is_win: bool,
        turn_count: Optional[int] = None
    ) -> Optional[User]:
        """점수 업데이트"""
        user = await self.get_by_id(user_id)
        if not user:
            return None

        # 점수 업데이트 (최소 0)
        user.score = max(0, user.score + score_change)

        # 승패 업데이트
        if is_win:
            user.wins += 1
            # 최단 턴 업데이트
            if turn_count and (user.best_turn_count is None or turn_count < user.best_turn_count):
                user.best_turn_count = turn_count
        else:
            user.losses += 1

        await self.session.commit()
        await self.session.refresh(user)
        return user

    async def reset_stats(self, user_id: int) -> bool:
        """유저 통계 리셋 (일일 리셋용)"""
        user = await self.get_by_id(user_id)
        if not user:
            return False

        user.score = 0
        user.wins = 0
        user.losses = 0
        user.best_turn_count = None
        await self.session.commit()
        return True

    async def delete_user(self, user_id: int) -> bool:
        """유저 삭제"""
        user = await self.get_by_id(user_id)
        if not user:
            return False

        await self.session.delete(user)
        await self.session.commit()
        return True

    async def delete_inactive_users(self, exclude_user_id: Optional[int] = None) -> int:
        """게임 중이 아닌 유저 삭제 (일일 리셋용)"""
        query = delete(User).where(User.current_game_id == None)
        if exclude_user_id:
            query = query.where(User.id != exclude_user_id)

        result = await self.session.execute(query)
        await self.session.commit()
        return result.rowcount

    async def delete_all_users(self) -> int:
        """모든 유저 삭제"""
        result = await self.session.execute(delete(User))
        await self.session.commit()
        return result.rowcount


class RankingRepository:
    """랭킹 저장소"""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_leaderboard(self, limit: int = 20) -> list[User]:
        """리더보드 조회 (점수 > 승수 > 최단 턴)"""
        result = await self.session.execute(
            select(User)
            .order_by(
                User.score.desc(),
                User.wins.desc(),
                User.best_turn_count.asc().nullslast()
            )
            .limit(limit)
        )
        return list(result.scalars().all())

    async def get_top_user(self) -> Optional[User]:
        """1위 유저 조회"""
        result = await self.session.execute(
            select(User)
            .order_by(
                User.score.desc(),
                User.wins.desc(),
                User.best_turn_count.asc().nullslast()
            )
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def get_user_rank(self, user_id: int) -> int:
        """유저의 현재 순위 조회"""
        user = await self.session.execute(
            select(User).where(User.id == user_id)
        )
        target_user = user.scalar_one_or_none()
        if not target_user:
            return 0

        # 자신보다 높은 점수를 가진 유저 수 + 1
        count_result = await self.session.execute(
            select(func.count(User.id)).where(
                or_(
                    User.score > target_user.score,
                    and_(
                        User.score == target_user.score,
                        User.wins > target_user.wins
                    ),
                    and_(
                        User.score == target_user.score,
                        User.wins == target_user.wins,
                        User.best_turn_count < target_user.best_turn_count
                    ) if target_user.best_turn_count else False
                )
            )
        )
        return (count_result.scalar() or 0) + 1

    async def get_total_users(self) -> int:
        """총 유저 수"""
        result = await self.session.execute(select(func.count(User.id)))
        return result.scalar() or 0

    async def save_daily_champion(
        self,
        nickname: str,
        score: float,
        wins: int,
        losses: int,
        best_turn_count: Optional[int],
        champion_date: date,
        preserved_user_id: Optional[int] = None
    ) -> DailyChampion:
        """일일 챔피언 저장"""
        champion = DailyChampion(
            nickname=nickname,
            score=score,
            wins=wins,
            losses=losses,
            best_turn_count=best_turn_count,
            champion_date=champion_date,
            reset_at=datetime.utcnow(),
            preserved_user_id=preserved_user_id
        )
        self.session.add(champion)
        await self.session.commit()
        await self.session.refresh(champion)
        return champion

    async def get_champion_by_date(self, target_date: date) -> Optional[DailyChampion]:
        """특정 날짜의 챔피언 조회"""
        result = await self.session.execute(
            select(DailyChampion).where(DailyChampion.champion_date == target_date)
        )
        return result.scalar_one_or_none()

    async def get_recent_champions(self, days: int = 7) -> list[DailyChampion]:
        """최근 N일 챔피언 목록"""
        result = await self.session.execute(
            select(DailyChampion)
            .order_by(DailyChampion.champion_date.desc())
            .limit(days)
        )
        return list(result.scalars().all())

    async def get_yesterday_champion(self) -> Optional[DailyChampion]:
        """어제의 챔피언 조회"""
        from datetime import timedelta
        yesterday = date.today() - timedelta(days=1)
        return await self.get_champion_by_date(yesterday)
