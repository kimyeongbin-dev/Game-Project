"""
Ranking Router
랭킹 관련 API
"""

from typing import Optional
from fastapi import APIRouter, Header, HTTPException, status, Query

from database import get_db_session, is_db_available
from database.repository import UserRepository, RankingRepository
from schemas.ranking import (
    LeaderboardResponse, LeaderboardEntry,
    MyRankResponse, ChampionResponse, ChampionsResponse, DailyChampionEntry
)
from routers.users import get_current_user

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

        # 전날 챔피언 조회
        yesterday_champion = await ranking_repo.get_yesterday_champion()
        champion_nickname = yesterday_champion.nickname if yesterday_champion else None

        entries = []
        for idx, user in enumerate(users, start=1):
            entries.append(LeaderboardEntry(
                rank=idx,
                nickname=user.nickname,
                score=user.score,
                wins=user.wins,
                losses=user.losses,
                best_turn_count=user.best_turn_count,
                is_champion=(user.nickname == champion_nickname)
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


@router.get("/champion", response_model=ChampionResponse)
async def get_yesterday_champion():
    """
    전날 챔피언 조회
    """
    if not is_db_available():
        return ChampionResponse(
            success=False,
            message="Database not available"
        )

    async for session in get_db_session():
        if session is None:
            return ChampionResponse(
                success=False,
                message="Database not available"
            )

        ranking_repo = RankingRepository(session)
        champion = await ranking_repo.get_yesterday_champion()

        if not champion:
            return ChampionResponse(
                success=True,
                champion=None,
                message="아직 챔피언이 없습니다"
            )

        return ChampionResponse(
            success=True,
            champion=DailyChampionEntry(
                date=champion.champion_date.isoformat(),
                nickname=champion.nickname,
                score=champion.score,
                wins=champion.wins,
                losses=champion.losses,
                best_turn_count=champion.best_turn_count
            ),
            message="전날 챔피언 조회 성공"
        )


@router.get("/champions", response_model=ChampionsResponse)
async def get_recent_champions(days: int = Query(7, ge=1, le=30)):
    """
    최근 N일 챔피언 목록 조회
    """
    if not is_db_available():
        return ChampionsResponse(champions=[], count=0)

    async for session in get_db_session():
        if session is None:
            return ChampionsResponse(champions=[], count=0)

        ranking_repo = RankingRepository(session)
        champions = await ranking_repo.get_recent_champions(days)

        entries = [
            DailyChampionEntry(
                date=c.champion_date.isoformat(),
                nickname=c.nickname,
                score=c.score,
                wins=c.wins,
                losses=c.losses,
                best_turn_count=c.best_turn_count
            )
            for c in champions
        ]

        return ChampionsResponse(
            champions=entries,
            count=len(entries)
        )
