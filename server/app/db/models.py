"""
Database Models
SQLAlchemy 모델 정의

정본은 docs/api/platform.md §5 와 이 파일뿐이다.
인원·게임·모드 수를 스키마에 박지 않는다 — 좌석은 행으로, game·mode·status 는
DB ENUM 이 아닌 문자열로 둔다. 값 추가에 마이그레이션이 필요 없어야 한다.
"""

from sqlalchemy import Column, String, DateTime, Boolean, Integer, Float, ForeignKey
from sqlalchemy.orm import relationship

from app.core.time import utcnow

from .config import Base


# ===== 유저 및 랭킹 관련 모델 =====

class User(Base):
    """
    User 테이블
    - 닉네임 + 비밀번호 기반 등록
    - 세션 토큰으로 인증
    """
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, autoincrement=True)
    nickname = Column(String(20), unique=True, nullable=False, index=True)
    password_hash = Column(String(128), nullable=False)  # bcrypt 해시
    session_token = Column(String(64), unique=True, nullable=False, index=True)

    # 랭킹 정보
    score = Column(Float, default=0, nullable=False)  # 총 점수 (턴 보너스 포함)
    wins = Column(Integer, default=0, nullable=False)
    losses = Column(Integer, default=0, nullable=False)
    best_turn_count = Column(Integer, nullable=True)  # 최단 턴 (승리 시)

    # 접속 상태
    is_online = Column(Boolean, default=False, nullable=False)
    current_game_id = Column(String(36), nullable=True)
    last_active_at = Column(DateTime, default=utcnow, nullable=False)

    # 타임스탬프
    created_at = Column(DateTime, default=utcnow, nullable=False)

    def __repr__(self):
        return f"<User(id={self.id}, nickname={self.nickname}, score={self.score})>"


# ===== 게임 기록 =====

class GameSession(Base):
    """
    게임 한 판의 시작·종료 기록

    진행 중 상태(좌석 위치·벽·차례)는 담지 않는다 — 권위는 Redis
    `game:<id>:state` 다 (docs/api/games/maze.md §8). DB 는 시작 시 행을 만들고
    종료 시 결과를 채운다. `status == "in_progress"` 인 행은 §8 fail-safe 가
    "Redis 상태가 사라진 진행 중 게임"을 찾는 기준이다.
    """
    __tablename__ = "game_sessions"

    game_id = Column(String(36), primary_key=True)

    game = Column(String(32), nullable=False)          # maze_1p, …
    mode = Column(String(16), nullable=False)          # duel, trio, …
    is_ranked = Column(Boolean, default=False, nullable=False)

    status = Column(String(16), default="in_progress", nullable=False, index=True)
    end_reason = Column(String(16), nullable=True)     # goal_reached | last_standing | server_fault
    winner_seat_no = Column(Integer, nullable=True)
    turn_count = Column(Integer, default=0, nullable=False)

    started_at = Column(DateTime, default=utcnow, nullable=False)
    ended_at = Column(DateTime, nullable=True)

    participants = relationship(
        "GameParticipant",
        back_populates="session",
        order_by="GameParticipant.seat_no",
        cascade="all, delete-orphan",
        passive_deletes=True,
        lazy="selectin",  # async 세션은 지연 로딩을 못 한다
    )

    def __repr__(self):
        return f"<GameSession(game_id={self.game_id}, status={self.status})>"


class GameParticipant(Base):
    """
    좌석 하나 = 행 하나. 인원이 늘어도 행만 는다 (platform.md §5)
    """
    __tablename__ = "game_participants"

    game_id = Column(
        String(36),
        ForeignKey("game_sessions.game_id", ondelete="CASCADE"),
        primary_key=True,
    )
    seat_no = Column(Integer, primary_key=True)        # 1..N

    user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)  # AI 면 null
    display_name = Column(String(50), nullable=False)
    is_ai = Column(Boolean, default=False, nullable=False)

    # 종료 시 기록
    result = Column(String(16), nullable=True)         # win | lose | draw | abandoned | void
    rank = Column(Integer, nullable=True)
    elimination_reason = Column(String(32), nullable=True)
    mmr_before = Column(Integer, nullable=True)        # 랭크전만
    mmr_after = Column(Integer, nullable=True)

    session = relationship("GameSession", back_populates="participants")

    def __repr__(self):
        return f"<GameParticipant(game_id={self.game_id}, seat_no={self.seat_no})>"
