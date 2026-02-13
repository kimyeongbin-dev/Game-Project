"""
Ranking Schemas
랭킹 관련 Pydantic 모델
"""

from typing import Optional
from pydantic import BaseModel, Field

from schemas.users import ResetTimeInfo


class LeaderboardEntry(BaseModel):
    """리더보드 항목"""
    rank: int
    nickname: str
    score: float
    wins: int
    losses: int
    best_turn_count: Optional[int] = None
    is_champion: bool = False  # 전날 챔피언 표시


class LeaderboardResponse(BaseModel):
    """리더보드 응답"""
    entries: list[LeaderboardEntry]
    total_players: int
    yesterday_champion: Optional["DailyChampionEntry"] = None  # 전날 챔피언 정보
    reset_info: Optional[ResetTimeInfo] = None  # 다음 리셋 시간 정보


class MyRankResponse(BaseModel):
    """내 순위 응답"""
    rank: int
    nickname: str
    score: float
    wins: int
    losses: int
    best_turn_count: Optional[int] = None
    total_players: int


class DailyChampionEntry(BaseModel):
    """일일 챔피언 항목"""
    date: str
    nickname: str
    score: float
    wins: int
    losses: int = 0
    best_turn_count: Optional[int] = None


class ChampionResponse(BaseModel):
    """챔피언 응답 (단일)"""
    success: bool
    champion: Optional[DailyChampionEntry] = None
    message: str


class ChampionsResponse(BaseModel):
    """챔피언 목록 응답"""
    champions: list[DailyChampionEntry]
    count: int


# ===== 점수 계산 관련 =====

class ScoreCalculation(BaseModel):
    """점수 계산 결과"""
    base_score: int = Field(..., description="기본 점수 (+3 승리, -1 패배)")
    turn_bonus: float = Field(..., description="턴 보너스 (10/turn_count)")
    total_change: float = Field(..., description="총 점수 변화")


class GameResultResponse(BaseModel):
    """게임 결과 응답 (점수 반영 후)"""
    success: bool
    is_winner: bool
    score_before: float
    score_after: float
    score_change: ScoreCalculation
    new_rank: int
    message: str
