"""
User & Auth Schemas
유저 관련 Pydantic 모델
"""

from typing import Optional, List
from pydantic import BaseModel, Field


# ===== System Info Schemas =====

class ResetTimeInfo(BaseModel):
    """리셋 시간 정보"""
    next_reset_at: str = Field(..., description="다음 리셋 시간 (KST, ISO 형식)")
    time_remaining: str = Field(..., description="리셋까지 남은 시간 (HH:MM:SS)")
    reset_hour_kst: int = Field(default=9, description="리셋 시간 (KST 기준)")


# ===== Request Schemas =====

class RegisterRequest(BaseModel):
    """유저 등록 요청"""
    nickname: str = Field(..., min_length=2, max_length=12, description="닉네임 (2-12자, 영문/숫자/한글)")
    password: str = Field(..., min_length=4, max_length=50, description="비밀번호 (4-50자)")


class LoginRequest(BaseModel):
    """로그인 요청"""
    nickname: str = Field(..., min_length=2, max_length=12)
    password: str = Field(..., min_length=4, max_length=50)


# ===== Response Schemas =====

class UserInfoResponse(BaseModel):
    """유저 정보 응답"""
    user_id: int
    nickname: str
    score: float
    wins: int
    losses: int
    best_turn_count: Optional[int] = None
    rank: Optional[int] = None
    is_champion: bool = False  # 전날 챔피언 여부
    reset_info: Optional[ResetTimeInfo] = None  # 리셋 시간 정보


class RegisterResponse(BaseModel):
    """등록 응답"""
    success: bool
    user_id: Optional[int] = None
    nickname: Optional[str] = None
    session_token: Optional[str] = None
    reset_info: Optional[ResetTimeInfo] = None
    message: str
    error: Optional[str] = None


class LoginResponse(BaseModel):
    """로그인 응답"""
    success: bool
    user_id: Optional[int] = None
    nickname: Optional[str] = None
    session_token: Optional[str] = None
    score: float = 0
    wins: int = 0
    losses: int = 0
    best_turn_count: Optional[int] = None
    reset_info: Optional[ResetTimeInfo] = None
    message: str
    error: Optional[str] = None


class HeartbeatResponse(BaseModel):
    """Heartbeat 응답"""
    success: bool
    message: str


class LogoutResponse(BaseModel):
    """로그아웃 응답"""
    success: bool
    message: str


# ===== Game History Export Schemas =====

class GameHistoryExportEntry(BaseModel):
    """내보내기용 게임 내역 항목"""
    game_id: str
    game_mode: str
    opponent_name: str
    result: str  # "win", "lose", "abandoned"
    turn_count: int
    score_change: Optional[float] = None
    created_at: str
    finished_at: Optional[str] = None


class GameHistoryExportResponse(BaseModel):
    """게임 내역 내보내기 응답"""
    nickname: str
    export_time: str
    total_games: int
    games: List[GameHistoryExportEntry]
    summary: dict  # 통계 요약
