"""
Ranking Service
점수 계산 및 랭킹 관리
"""

from typing import Optional
from database.repository import UserRepository, RankingRepository
from sqlalchemy.ext.asyncio import AsyncSession


class RankingService:
    """랭킹 점수 계산 및 관리 서비스"""

    # 점수 상수
    WIN_POINTS = 3      # 승리 시 기본 점수
    LOSS_POINTS = -1    # 패배 시 기본 점수
    TURN_BONUS_BASE = 10.0  # 턴 보너스 기준

    def __init__(self, session: AsyncSession):
        self.session = session
        self.user_repo = UserRepository(session)
        self.ranking_repo = RankingRepository(session)

    def calculate_score(self, is_winner: bool, turn_count: int) -> dict:
        """
        게임 결과에 따른 점수 계산

        Args:
            is_winner: 승리 여부
            turn_count: 게임 종료 시 총 턴 수

        Returns:
            {
                "base_score": int,      # 기본 점수 (+3/-1)
                "turn_bonus": float,    # 턴 보너스 (승리 시만)
                "total_change": float   # 총 점수 변화
            }
        """
        if is_winner:
            base_score = self.WIN_POINTS
            # 턴 보너스: 10 / turn_count (빠른 승리일수록 높은 보너스)
            turn_bonus = round(self.TURN_BONUS_BASE / max(turn_count, 1), 2)
        else:
            base_score = self.LOSS_POINTS
            turn_bonus = 0.0

        total_change = base_score + turn_bonus

        return {
            "base_score": base_score,
            "turn_bonus": turn_bonus,
            "total_change": round(total_change, 2)
        }

    async def update_game_result(
        self,
        user_id: int,
        is_winner: bool,
        turn_count: int
    ) -> Optional[dict]:
        """
        게임 결과 반영 및 점수 업데이트

        Returns:
            {
                "score_before": float,
                "score_after": float,
                "score_change": dict,
                "new_rank": int
            }
        """
        user = await self.user_repo.get_by_id(user_id)
        if not user:
            return None

        score_before = user.score

        # 점수 계산
        score_change = self.calculate_score(is_winner, turn_count)

        # 유저 점수 업데이트
        await self.user_repo.update_score(
            user_id=user_id,
            score_change=score_change["total_change"],
            is_win=is_winner,
            turn_count=turn_count if is_winner else None
        )

        # 새 순위 조회
        new_rank = await self.ranking_repo.get_user_rank(user_id)

        # 업데이트된 유저 정보 조회
        updated_user = await self.user_repo.get_by_id(user_id)

        return {
            "score_before": score_before,
            "score_after": updated_user.score,
            "score_change": score_change,
            "new_rank": new_rank
        }

    async def get_leaderboard(self, limit: int = 20) -> list[dict]:
        """리더보드 조회"""
        users = await self.ranking_repo.get_leaderboard(limit)
        yesterday_champion = await self.ranking_repo.get_yesterday_champion()
        champion_nickname = yesterday_champion.nickname if yesterday_champion else None

        result = []
        for idx, user in enumerate(users, start=1):
            result.append({
                "rank": idx,
                "nickname": user.nickname,
                "score": user.score,
                "wins": user.wins,
                "losses": user.losses,
                "best_turn_count": user.best_turn_count,
                "is_champion": user.nickname == champion_nickname
            })

        return result

    async def get_user_rank_info(self, user_id: int) -> Optional[dict]:
        """유저 순위 정보 조회"""
        user = await self.user_repo.get_by_id(user_id)
        if not user:
            return None

        rank = await self.ranking_repo.get_user_rank(user_id)
        total = await self.ranking_repo.get_total_users()

        return {
            "rank": rank,
            "nickname": user.nickname,
            "score": user.score,
            "wins": user.wins,
            "losses": user.losses,
            "best_turn_count": user.best_turn_count,
            "total_players": total
        }


# 싱글톤 인스턴스 생성 함수
async def get_ranking_service(session: AsyncSession) -> RankingService:
    """RankingService 인스턴스 생성"""
    return RankingService(session)
