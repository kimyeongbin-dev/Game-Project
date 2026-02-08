"""
User & Auth Schemas
유저 관련 Pydantic 모델
"""

from typing import Optional
from pydantic import BaseModel, Field


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


class RegisterResponse(BaseModel):
    """등록 응답"""
    success: bool
    user_id: Optional[int] = None
    nickname: Optional[str] = None
    session_token: Optional[str] = None
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
