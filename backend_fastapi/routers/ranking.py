"""
Ranking Router
랭킹 관련 API
"""

import logging
from typing import Optional
from fastapi import APIRouter, Header, HTTPException, status, Query, Request

logger = logging.getLogger(__name__)

from database import get_db_session, is_db_available
from database.repository import UserRepository, RankingRepository
from database.memory_store import memory_store
from middleware.rate_limiter import limiter
from schemas.ranking import (
    LeaderboardResponse, LeaderboardEntry,
    MyRankResponse, ChampionResponse, ChampionsResponse, DailyChampionEntry
)
from schemas.users import ResetTimeInfo
from routers.users import get_current_user, get_reset_time_info

router = APIRouter(prefix="/api/v1/ranking", tags=["Ranking"])


@router.get("/leaderboard", response_model=LeaderboardResponse)
@limiter.limit("30/minute")
async def get_leaderboard(request: Request, limit: int = Query(20, ge=1, le=100)):
    """
    리더보드 조회
    - 점수 > 승수 > 최단 턴 순으로 정렬
    - 기본 20위까지
    """
    # DB가 없으면 인메모리 스토어 사용
    if not is_db_available():
        users = memory_store.get_leaderboard(limit)
        total = memory_store.get_total_users()
        yesterday_champion = memory_store.get_yesterday_champion()
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

        champion_entry = None
        if yesterday_champion:
            champion_entry = DailyChampionEntry(
                date=yesterday_champion.champion_date.isoformat(),
                nickname=yesterday_champion.nickname,
                score=yesterday_champion.score,
                wins=yesterday_champion.wins,
                losses=yesterday_champion.losses,
                best_turn_count=yesterday_champion.best_turn_count
            )

        return LeaderboardResponse(
            entries=entries,
            total_players=total,
            yesterday_champion=champion_entry,
            reset_info=get_reset_time_info()
        )

    async for session in get_db_session():
        if session is None:
            return LeaderboardResponse(
                entries=[],
                total_players=0,
                reset_info=get_reset_time_info()
            )

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

        # 전날 챔피언 정보 구성
        champion_entry = None
        if yesterday_champion:
            champion_entry = DailyChampionEntry(
                date=yesterday_champion.champion_date.isoformat(),
                nickname=yesterday_champion.nickname,
                score=yesterday_champion.score,
                wins=yesterday_champion.wins,
                losses=yesterday_champion.losses,
                best_turn_count=yesterday_champion.best_turn_count
            )

        return LeaderboardResponse(
            entries=entries,
            total_players=total,
            yesterday_champion=champion_entry,
            reset_info=get_reset_time_info()
        )


@router.get("/my-rank", response_model=MyRankResponse)
@limiter.limit("30/minute")
async def get_my_rank(request: Request, authorization: Optional[str] = Header(None)):
    """
    내 순위 조회
    """
    user = await get_current_user(authorization)

    # DB가 없으면 인메모리 스토어 사용
    if not is_db_available():
        rank = memory_store.get_user_rank(user.id)
        total = memory_store.get_total_users()
        return MyRankResponse(
            rank=rank,
            nickname=user.nickname,
            score=user.score,
            wins=user.wins,
            losses=user.losses,
            best_turn_count=user.best_turn_count,
            total_players=total
        )

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
@limiter.limit("30/minute")
async def get_yesterday_champion(request: Request):
    """
    전날 챔피언 조회
    """
    # DB가 없으면 인메모리 스토어 사용
    if not is_db_available():
        champion = memory_store.get_yesterday_champion()
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
@limiter.limit("20/minute")
async def get_recent_champions(request: Request, days: int = Query(7, ge=1, le=30)):
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
