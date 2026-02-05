"""
Database Models
SQLAlchemy 모델 정의
"""

from datetime import datetime
from sqlalchemy import Column, String, DateTime, Boolean, Integer, Enum as SQLEnum
from sqlalchemy.dialects.postgresql import JSONB
import enum

from .config import Base


class GameStatus(enum.Enum):
    """게임 상태"""
    IN_PROGRESS = "in_progress"
    FINISHED = "finished"
    ABANDONED = "abandoned"


class GameMode(enum.Enum):
    """게임 모드"""
    VS_AI = "vs_ai"
    LOCAL_2P = "local_2p"


class GameSession(Base):
    """
    게임 세션 테이블

    게임의 전체 상태를 JSONB로 저장하여 유연하게 관리
    game_history는 모든 수의 기록을 배열로 저장하여 리플레이 기능 지원
    """
    __tablename__ = "game_sessions"

    # 기본 키: 게임 ID (UUID 문자열)
    game_id = Column(String(36), primary_key=True, index=True)

    # 게임 메타 정보
    status = Column(
        SQLEnum(GameStatus, name="game_status"),
        default=GameStatus.IN_PROGRESS,
        nullable=False
    )
    game_mode = Column(
        SQLEnum(GameMode, name="game_mode"),
        default=GameMode.VS_AI,
        nullable=False
    )

    # 플레이어 정보
    player1_name = Column(String(50), nullable=False, default="Player")
    player2_name = Column(String(50), nullable=False, default="AI")

    # 게임 진행 정보
    current_turn = Column(Integer, default=1, nullable=False)
    turn_count = Column(Integer, default=0, nullable=False)
    winner = Column(Integer, nullable=True)

    # AI 설정 (vs_ai 모드일 때)
    ai_difficulty = Column(String(20), nullable=True, default="normal")

    # 게임 상태 (전체 상태를 JSONB로 저장)
    # 포함 내용: board, players (positions, walls_remaining), walls
    game_state = Column(JSONB, nullable=False)

    # 게임 히스토리 (리플레이용 - 모든 수의 기록)
    # 배열 형태: [{"turn": 1, "player": 1, "action": {...}, "timestamp": "..."}, ...]
    game_history = Column(JSONB, nullable=False, default=list)

    # 타임스탬프
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    # 삭제 여부 (소프트 삭제)
    is_deleted = Column(Boolean, default=False, nullable=False)

    def __repr__(self):
        return f"<GameSession(game_id={self.game_id}, status={self.status.value})>"
