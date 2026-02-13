"""
Database Models
SQLAlchemy 모델 정의
"""

from datetime import datetime, date
from sqlalchemy import Column, String, DateTime, Date, Boolean, Integer, Float, Enum as SQLEnum, ForeignKey, JSON
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
    """
    게임 모드
    - VS_AI: AI 대전 (일반 대전) - 로그인 필요, 랭킹 미반영
    - RANKED: 랭킹전 (온라인 2P 대전) - 로그인 필요, 랭킹 반영
    - FRIEND_MATCH: 친구대전 (방 코드 기반) - 로그인 필요, 랭킹 미반영
    """
    VS_AI = "vs_ai"              # AI 대전 (일반 대전)
    RANKED = "ranked"            # 랭킹전 (온라인 2P 대전)
    FRIEND_MATCH = "friend_match"  # 친구대전 (방 코드 기반)


# ===== 유저 및 랭킹 관련 모델 =====

class User(Base):
    """
    User 테이블
    - 닉네임 + 비밀번호 기반 등록
    - 세션 토큰으로 인증 (만료 시간 포함)
    """
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, autoincrement=True)
    nickname = Column(String(20), unique=True, nullable=False, index=True)
    password_hash = Column(String(128), nullable=False)  # bcrypt 해시
    session_token = Column(String(64), unique=True, nullable=False, index=True)
    token_expires_at = Column(DateTime, nullable=True, index=True)  # 토큰 만료 시간

    # 랭킹 정보
    score = Column(Float, default=0, nullable=False)  # 총 점수 (턴 보너스 포함)
    wins = Column(Integer, default=0, nullable=False)
    losses = Column(Integer, default=0, nullable=False)
    best_turn_count = Column(Integer, nullable=True)  # 최단 턴 (승리 시)

    # 접속 상태
    is_online = Column(Boolean, default=False, nullable=False)
    current_game_id = Column(String(36), nullable=True)
    last_active_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    # 타임스탬프
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    def is_token_valid(self) -> bool:
        """토큰이 유효한지 확인 (만료되지 않았는지)"""
        if self.token_expires_at is None:
            return True  # 만료 시간이 없으면 유효
        return datetime.utcnow() < self.token_expires_at

    def __repr__(self):
        return f"<User(id={self.id}, nickname={self.nickname}, score={self.score})>"


class DailyChampion(Base):
    """
    일일 챔피언 기록 테이블
    - 매일 KST 09:00 리셋 시 1위 기록 저장
    """
    __tablename__ = "daily_champions"

    id = Column(Integer, primary_key=True, autoincrement=True)

    # 챔피언 정보 (리셋 시점 스냅샷)
    nickname = Column(String(20), nullable=False)
    score = Column(Float, nullable=False)
    wins = Column(Integer, nullable=False)
    losses = Column(Integer, default=0, nullable=False)
    best_turn_count = Column(Integer, nullable=True)

    # 날짜 정보
    champion_date = Column(Date, nullable=False, index=True)  # 챔피언이 된 날짜
    reset_at = Column(DateTime, nullable=False)  # 리셋 시각

    # 다음날 유지된 유저 ID (리셋 후에도 유지)
    preserved_user_id = Column(Integer, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    def __repr__(self):
        return f"<DailyChampion(date={self.champion_date}, nickname={self.nickname}, score={self.score})>"


# ===== 온라인 2P 매칭 관련 모델 =====

class MatchQueueStatus(enum.Enum):
    """매칭 대기열 상태"""
    WAITING = "waiting"
    MATCHED = "matched"
    CANCELLED = "cancelled"


class MatchQueue(Base):
    """
    자동 매칭 대기열
    """
    __tablename__ = "match_queue"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)

    status = Column(
        SQLEnum(MatchQueueStatus, name="match_queue_status"),
        default=MatchQueueStatus.WAITING,
        nullable=False
    )
    matched_user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    matched_game_id = Column(String(36), nullable=True)

    joined_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    matched_at = Column(DateTime, nullable=True)

    # 관계
    user = relationship("User", foreign_keys=[user_id], backref="queue_entries")

    def __repr__(self):
        return f"<MatchQueue(user_id={self.user_id}, status={self.status.value})>"


class RoomStatus(enum.Enum):
    """방 상태"""
    WAITING = "waiting"   # 호스트만 있음
    READY = "ready"       # 게스트 입장
    PLAYING = "playing"   # 게임 진행 중
    CLOSED = "closed"     # 방 닫힘


class GameRoom(Base):
    """
    방 코드 기반 대기실
    """
    __tablename__ = "game_rooms"

    id = Column(Integer, primary_key=True, autoincrement=True)
    room_code = Column(String(6), unique=True, nullable=False, index=True)

    host_user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    guest_user_id = Column(Integer, ForeignKey("users.id"), nullable=True)

    status = Column(
        SQLEnum(RoomStatus, name="room_status"),
        default=RoomStatus.WAITING,
        nullable=False
    )
    game_id = Column(String(36), nullable=True)  # 게임 시작 시 연결

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    # 관계
    host = relationship("User", foreign_keys=[host_user_id], backref="hosted_rooms")
    guest = relationship("User", foreign_keys=[guest_user_id], backref="joined_rooms")

    def __repr__(self):
        return f"<GameRoom(code={self.room_code}, status={self.status.value})>"


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

    # 랭킹전 관련
    is_ranked = Column(Boolean, default=False, nullable=False)
    player1_user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    player2_user_id = Column(Integer, ForeignKey("users.id"), nullable=True)  # 온라인 2P일 때

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
