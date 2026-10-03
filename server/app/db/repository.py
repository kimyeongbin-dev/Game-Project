"""
Repositories
게임 기록·유저·랭킹 데이터베이스 CRUD 작업
"""

import re
import secrets
from dataclasses import dataclass
from typing import Optional, Sequence

import bcrypt
from sqlalchemy import select, func, and_, or_
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.time import utcnow

from .models import GameParticipant, GameSession, User


# ===== 게임 기록 Repository =====

# 문자열 컬럼의 허용 값. DB ENUM·CHECK 를 두지 않으므로 여기서 검증한다
# (값 추가에 마이그레이션이 필요 없어야 한다 — platform.md §5).
END_REASONS = ("goal_reached", "last_standing", "server_fault")
RESULTS = ("win", "lose", "draw", "abandoned", "void")
ELIMINATION_REASONS = ("surrender", "time_forfeit", "disconnect_forfeit")


@dataclass(frozen=True)
class ParticipantSeed:
    """게임 시작 시 좌석 하나"""
    seat_no: int
    user_id: Optional[int]
    display_name: str
    is_ai: bool = False


@dataclass(frozen=True)
class SeatResult:
    """게임 종료 시 좌석 하나의 결과"""
    seat_no: int
    result: str
    rank: Optional[int]
    elimination_reason: Optional[str] = None
    mmr_before: Optional[int] = None
    mmr_after: Optional[int] = None


def _require_seats_1_to_n(seat_nos: Sequence[int]) -> None:
    """좌석 번호가 1..N 연속·중복 없음인지. N 은 가정하지 않는다"""
    if sorted(seat_nos) != list(range(1, len(seat_nos) + 1)):
        raise ValueError(f"seat_no must be 1..N without gaps or duplicates: {sorted(seat_nos)}")


class GameSessionRepository:
    """
    게임 기록 저장소 — 시작 시 행 생성, 종료 시 결과 기록

    진행 중 상태는 쓰지 않는다 (Redis 권위, maze.md §8).
    """

    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(
        self,
        game_id: str,
        *,
        game: str,
        mode: str,
        is_ranked: bool,
        participants: Sequence[ParticipantSeed],
    ) -> GameSession:
        """게임 시작 기록. 좌석은 1..N 이어야 한다"""
        if len(participants) < 2:
            raise ValueError("a game needs at least 2 participants")
        _require_seats_1_to_n([p.seat_no for p in participants])

        game_session = GameSession(
            game_id=game_id,
            game=game,
            mode=mode,
            is_ranked=is_ranked,
            status="in_progress",
            participants=[
                GameParticipant(
                    seat_no=p.seat_no,
                    user_id=p.user_id,
                    display_name=p.display_name,
                    is_ai=p.is_ai,
                )
                for p in participants
            ],
        )
        self.session.add(game_session)
        await self.session.commit()
        return await self.get_by_id(game_id)

    async def get_by_id(self, game_id: str) -> Optional[GameSession]:
        """게임 기록 조회 (participants 는 seat_no 순)"""
        result = await self.session.execute(
            select(GameSession)
            .where(GameSession.game_id == game_id)
            .execution_options(populate_existing=True)
        )
        return result.scalar_one_or_none()

    async def record_result(
        self,
        game_id: str,
        *,
        end_reason: str,
        winner_seat_no: Optional[int],
        turn_count: int,
        results: Sequence[SeatResult],
    ) -> Optional[GameSession]:
        """
        게임 종료 기록. 좌석 전원의 결과가 있어야 하고, 종료는 한 번뿐이다

        server_fault 무효 처리는 void() 를 쓴다.
        """
        if end_reason not in END_REASONS or end_reason == "server_fault":
            raise ValueError(f"Invalid end_reason: {end_reason}")
        for r in results:
            if r.result not in RESULTS:
                raise ValueError(f"Invalid result: {r.result}")
            if r.elimination_reason is not None and r.elimination_reason not in ELIMINATION_REASONS:
                raise ValueError(f"Invalid elimination_reason: {r.elimination_reason}")

        game_session = await self.get_by_id(game_id)
        if not game_session:
            return None
        if game_session.status != "in_progress":
            raise ValueError(f"Game {game_id} already ended ({game_session.status})")

        by_seat = {r.seat_no: r for r in results}
        if len(by_seat) != len(results) or set(by_seat) != {p.seat_no for p in game_session.participants}:
            raise ValueError("results must cover every seat exactly once")
        if winner_seat_no is not None and winner_seat_no not in by_seat:
            raise ValueError(f"Invalid winner_seat_no: {winner_seat_no}")

        for participant in game_session.participants:
            r = by_seat[participant.seat_no]
            participant.result = r.result
            participant.rank = r.rank
            participant.elimination_reason = r.elimination_reason
            participant.mmr_before = r.mmr_before
            participant.mmr_after = r.mmr_after

        game_session.status = "finished"
        game_session.end_reason = end_reason
        game_session.winner_seat_no = winner_seat_no
        game_session.turn_count = turn_count
        game_session.ended_at = utcnow()

        await self.session.commit()
        return await self.get_by_id(game_id)

    async def void(self, game_id: str) -> Optional[GameSession]:
        """
        서버 장애 무효 처리 (maze.md §8) — 전원 result=void, MMR 변동 없음
        """
        game_session = await self.get_by_id(game_id)
        if not game_session:
            return None
        if game_session.status != "in_progress":
            raise ValueError(f"Game {game_id} already ended ({game_session.status})")

        for participant in game_session.participants:
            participant.result = "void"
            participant.rank = None
            participant.mmr_before = None
            participant.mmr_after = None

        game_session.status = "void"
        game_session.end_reason = "server_fault"
        game_session.winner_seat_no = None
        game_session.ended_at = utcnow()

        await self.session.commit()
        return await self.get_by_id(game_id)

    async def list_in_progress(self, limit: int = 100, offset: int = 0) -> list[GameSession]:
        """진행 중으로 기록된 게임 (오래된 순, 페이지) — §8 fail-safe 점검용"""
        result = await self.session.execute(
            select(GameSession)
            .where(GameSession.status == "in_progress")
            .order_by(GameSession.started_at, GameSession.game_id)
            .limit(limit)
            .offset(offset)
        )
        return list(result.scalars().all())


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
            last_active_at=utcnow()
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
        user.last_active_at = utcnow()
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
        user.last_active_at = utcnow()
        await self.session.commit()
        return True

    async def set_current_game(self, user_id: int, game_id: Optional[str]) -> bool:
        """현재 게임 ID 설정"""
        user = await self.get_by_id(user_id)
        if not user:
            return False

        user.current_game_id = game_id
        user.last_active_at = utcnow()
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

    async def delete_user(self, user_id: int) -> bool:
        """유저 삭제"""
        user = await self.get_by_id(user_id)
        if not user:
            return False

        await self.session.delete(user)
        await self.session.commit()
        return True


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
