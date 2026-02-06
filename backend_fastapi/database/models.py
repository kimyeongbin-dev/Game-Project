"""
Database Models
SQLAlchemy 모델 정의
"""

from datetime import datetime
from sqlalchemy import Column, String, DateTime, Boolean, Integer, Enum as SQLEnum, ForeignKey, JSON
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship
import enum


# PostgreSQL에서는 JSONB 사용, 다른 DB에서는 JSON 사용
JsonType = JSON().with_variant(JSONB(), 'postgresql')

from .config import Base


class GameStatus(enum.Enum):
    """게임 상태"""
    IN_PROGRESS = "in_progress"
    PLAYER1_WIN = "player1_win"    # Player 1 승리
    PLAYER2_WIN = "player2_win"    # Player 2 / AI 승리
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

    # AI 설정 (vs_ai 모드일 때만 사용)
    ai_difficulty = Column(String(20), nullable=True)

    # 게임 상태 (전체 상태를 JSON으로 저장)
    # 포함 내용: board, players (positions, walls_remaining), walls
    game_state = Column(JsonType, nullable=False)

    # 게임 히스토리 (리플레이용 - 모든 수의 기록)
    # 배열 형태: [{"turn": 1, "player": 1, "action": {...}, "timestamp": "..."}, ...]
    game_history = Column(JsonType, nullable=False, default=list)

    # 타임스탬프
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    # 삭제 여부 (소프트 삭제)
    is_deleted = Column(Boolean, default=False, nullable=False)

    # 관계: 게임 히스토리 (1:N)
    moves = relationship("GameMove", back_populates="game_session", order_by="GameMove.step_no")

    def __repr__(self):
        return f"<GameSession(game_id={self.game_id}, status={self.status.value})>"


class ActionType(enum.Enum):
    """액션 타입"""
    MOVE = "move"
    WALL = "wall"


class GameMove(Base):
    """
    게임 히스토리 테이블 (개별 수 기록)

    각 이동/벽 설치를 개별 레코드로 저장하여 리플레이 기능 지원
    """
    __tablename__ = "game_moves"

    id = Column(Integer, primary_key=True, autoincrement=True)
    game_id = Column(String(36), ForeignKey("game_sessions.game_id"), nullable=False, index=True)

    # 수 번호 (0부터 시작, 순서대로 증가)
    step_no = Column(Integer, nullable=False)

    # 플레이어 정보
    player = Column(Integer, nullable=False)  # 1 또는 2

    # 액션 정보
    action_type = Column(SQLEnum(ActionType, name="action_type"), nullable=False)
    row = Column(Integer, nullable=False)
    col = Column(Integer, nullable=False)
    orientation = Column(String(20), nullable=True)  # wall일 때만 사용

    # 이 수를 둔 후의 게임 상태 스냅샷 (리플레이용)
    game_state_snapshot = Column(JsonType, nullable=False)

    # 타임스탬프
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    # 관계
    game_session = relationship("GameSession", back_populates="moves")

    def __repr__(self):
        return f"<GameMove(game_id={self.game_id}, step={self.step_no}, {self.action_type.value})>"

    def to_dict(self) -> dict:
        """딕셔너리로 변환"""
        result = {
            "step_no": self.step_no,
            "player": self.player,
            "action_type": self.action_type.value,
            "row": self.row,
            "col": self.col,
            "created_at": self.created_at.isoformat() + "Z"
        }
        if self.orientation:
            result["orientation"] = self.orientation
        return result
