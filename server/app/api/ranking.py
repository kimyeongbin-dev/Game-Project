"""
Ranking Router
랭킹 관련 API
"""

from typing import Optional
from fastapi import APIRouter, Header, HTTPException, status, Query

from app.db import get_db_session, is_db_available
from app.db.repository import UserRepository, RankingRepository
from app.schemas.ranking import (
    LeaderboardResponse, LeaderboardEntry,
    MyRankResponse
)
from app.api.users import get_current_user

router = APIRouter(prefix="/api/v1/ranking", tags=["Ranking"])


@router.get("/leaderboard", response_model=LeaderboardResponse)
async def get_leaderboard(limit: int = Query(20, ge=1, le=100)):
    """
    리더보드 조회
    - 점수 > 승수 > 최단 턴 순으로 정렬
    - 기본 20위까지
    """
    if not is_db_available():
        return LeaderboardResponse(entries=[], total_players=0)

    async for session in get_db_session():
        if session is None:
            return LeaderboardResponse(entries=[], total_players=0)

        ranking_repo = RankingRepository(session)

        # 리더보드 조회
        users = await ranking_repo.get_leaderboard(limit)
        total = await ranking_repo.get_total_users()

        entries = []
        for idx, user in enumerate(users, start=1):
            entries.append(LeaderboardEntry(
                rank=idx,
                nickname=user.nickname,
                score=user.score,
                wins=user.wins,
                losses=user.losses,
                best_turn_count=user.best_turn_count
            ))

        return LeaderboardResponse(
            entries=entries,
            total_players=total
        )


@router.get("/my-rank", response_model=MyRankResponse)
async def get_my_rank(authorization: Optional[str] = Header(None)):
    """
    내 순위 조회
    """
    user = await get_current_user(authorization)

    async for session in get_db_session():
        if session is None:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Database not available"
            )

        ranking_repo = RankingRepository(session)
        rank = await ranking_repo.get_user_rank(user.id)
        total = await ranking_repo.get_total_users()

        return MyRankResponse(
            rank=rank,
            nickname=user.nickname,
            score=user.score,
            wins=user.wins,
            losses=user.losses,
            best_turn_count=user.best_turn_count,
            total_players=total
        )
