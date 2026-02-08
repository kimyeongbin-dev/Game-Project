"""
Ranking Repository Tests
랭킹 시스템 테스트
"""

import pytest
from datetime import date, timedelta
from database.repository import UserRepository, RankingRepository


class TestRankingRepository:
    """랭킹 리포지토리 테스트"""

    async def test_get_leaderboard_empty(self, ranking_repository: RankingRepository):
        """빈 리더보드 테스트"""
        leaderboard = await ranking_repository.get_leaderboard()
        assert leaderboard == []

    async def test_get_leaderboard_single_user(
        self,
        user_repository: UserRepository,
        ranking_repository: RankingRepository
    ):
        """단일 유저 리더보드 테스트"""
        # 유저 생성
        await user_repository.create("solo", "password123")

        leaderboard = await ranking_repository.get_leaderboard()
        assert len(leaderboard) == 1
        assert leaderboard[0].nickname == "solo"

    async def test_get_leaderboard_sorted_by_score(
        self,
        user_repository: UserRepository,
        ranking_repository: RankingRepository
    ):
        """점수 기준 정렬 테스트"""
        # 유저 3명 생성
        user1, _ = await user_repository.create("low", "pass1234")
        user2, _ = await user_repository.create("high", "pass1234")
        user3, _ = await user_repository.create("mid", "pass1234")

        # 점수 설정
        await user_repository.update_score(user1.id, 10, True, 20)
        await user_repository.update_score(user2.id, 50, True, 15)
        await user_repository.update_score(user3.id, 30, True, 18)

        leaderboard = await ranking_repository.get_leaderboard()

        assert len(leaderboard) == 3
        assert leaderboard[0].nickname == "high"  # 50점
        assert leaderboard[1].nickname == "mid"   # 30점
        assert leaderboard[2].nickname == "low"   # 10점

    async def test_get_leaderboard_sorted_by_wins_on_tie(
        self,
        user_repository: UserRepository,
        ranking_repository: RankingRepository
    ):
        """동점 시 승수 기준 정렬 테스트"""
        # 유저 2명 생성 (같은 점수, 다른 승수)
        user1, _ = await user_repository.create("lesswins", "pass1234")
        user2, _ = await user_repository.create("morewins", "pass1234")

        # 같은 점수, 다른 승수
        await user_repository.update_score(user1.id, 10, True, 20)  # 1승
        await user_repository.update_score(user2.id, 5, True, 30)   # 1승
        await user_repository.update_score(user2.id, 5, True, 25)   # 2승

        leaderboard = await ranking_repository.get_leaderboard()

        # 점수 같으면 (10점) 승수가 많은 유저가 위
        assert leaderboard[0].nickname == "morewins"
        assert leaderboard[1].nickname == "lesswins"

    async def test_get_top_user(
        self,
        user_repository: UserRepository,
        ranking_repository: RankingRepository
    ):
        """1위 유저 조회 테스트"""
        # 유저 생성
        user1, _ = await user_repository.create("first", "pass1234")
        user2, _ = await user_repository.create("second", "pass1234")

        await user_repository.update_score(user1.id, 100, True, 10)
        await user_repository.update_score(user2.id, 50, True, 15)

        top_user = await ranking_repository.get_top_user()
        assert top_user is not None
        assert top_user.nickname == "first"

    async def test_get_user_rank(
        self,
        user_repository: UserRepository,
        ranking_repository: RankingRepository
    ):
        """유저 순위 조회 테스트"""
        # 유저 3명 생성
        user1, _ = await user_repository.create("rank1", "pass1234")
        user2, _ = await user_repository.create("rank2", "pass1234")
        user3, _ = await user_repository.create("rank3", "pass1234")

        await user_repository.update_score(user1.id, 100, True, 10)
        await user_repository.update_score(user2.id, 50, True, 15)
        await user_repository.update_score(user3.id, 25, True, 20)

        rank1 = await ranking_repository.get_user_rank(user1.id)
        rank2 = await ranking_repository.get_user_rank(user2.id)
        rank3 = await ranking_repository.get_user_rank(user3.id)

        assert rank1 == 1
        assert rank2 == 2
        assert rank3 == 3

    async def test_get_total_users(
        self,
        user_repository: UserRepository,
        ranking_repository: RankingRepository
    ):
        """총 유저 수 테스트"""
        # 초기 상태
        total = await ranking_repository.get_total_users()
        assert total == 0

        # 유저 추가
        await user_repository.create("user1", "pass1234")
        await user_repository.create("user2", "pass1234")
        await user_repository.create("user3", "pass1234")

        total = await ranking_repository.get_total_users()
        assert total == 3

    async def test_save_daily_champion(
        self,
        ranking_repository: RankingRepository
    ):
        """일일 챔피언 저장 테스트"""
        today = date.today()

        champion = await ranking_repository.save_daily_champion(
            nickname="champion",
            score=100.5,
            wins=20,
            losses=5,
            best_turn_count=12,
            champion_date=today,
            preserved_user_id=1
        )

        assert champion is not None
        assert champion.nickname == "champion"
        assert champion.score == 100.5
        assert champion.wins == 20
        assert champion.champion_date == today

    async def test_get_champion_by_date(
        self,
        ranking_repository: RankingRepository
    ):
        """날짜별 챔피언 조회 테스트"""
        today = date.today()
        yesterday = today - timedelta(days=1)

        # 챔피언 저장
        await ranking_repository.save_daily_champion(
            nickname="todaychamp",
            score=100,
            wins=20,
            losses=5,
            best_turn_count=12,
            champion_date=today
        )

        # 오늘 챔피언 조회
        champion = await ranking_repository.get_champion_by_date(today)
        assert champion is not None
        assert champion.nickname == "todaychamp"

        # 어제 챔피언 조회 (없음)
        yesterday_champion = await ranking_repository.get_champion_by_date(yesterday)
        assert yesterday_champion is None

    async def test_get_recent_champions(
        self,
        ranking_repository: RankingRepository
    ):
        """최근 챔피언 목록 테스트"""
        today = date.today()

        # 3일치 챔피언 저장
        for i in range(3):
            target_date = today - timedelta(days=i)
            await ranking_repository.save_daily_champion(
                nickname=f"champ{i}",
                score=100 - i * 10,
                wins=20 - i,
                losses=5,
                best_turn_count=12 + i,
                champion_date=target_date
            )

        # 최근 7일 챔피언 조회
        champions = await ranking_repository.get_recent_champions(7)
        assert len(champions) == 3

        # 날짜 내림차순 정렬 확인
        assert champions[0].nickname == "champ0"  # 오늘
        assert champions[1].nickname == "champ1"  # 어제
        assert champions[2].nickname == "champ2"  # 그저께


class TestRankingService:
    """랭킹 서비스 테스트"""

    async def test_calculate_score_win(self, async_session):
        """승리 점수 계산 테스트"""
        from services.ranking_service import RankingService

        service = RankingService(async_session)

        # 승리 (20턴)
        result = service.calculate_score(is_winner=True, turn_count=20)
        assert result["base_score"] == 3
        assert result["turn_bonus"] == 0.5  # 10/20
        assert result["total_change"] == 3.5

    async def test_calculate_score_win_fast(self, async_session):
        """빠른 승리 점수 계산 테스트"""
        from services.ranking_service import RankingService

        service = RankingService(async_session)

        # 빠른 승리 (10턴)
        result = service.calculate_score(is_winner=True, turn_count=10)
        assert result["base_score"] == 3
        assert result["turn_bonus"] == 1.0  # 10/10
        assert result["total_change"] == 4.0

    async def test_calculate_score_loss(self, async_session):
        """패배 점수 계산 테스트"""
        from services.ranking_service import RankingService

        service = RankingService(async_session)

        # 패배
        result = service.calculate_score(is_winner=False, turn_count=30)
        assert result["base_score"] == -1
        assert result["turn_bonus"] == 0
        assert result["total_change"] == -1

    async def test_update_game_result_win(
        self,
        user_repository: UserRepository,
        async_session
    ):
        """게임 결과 업데이트 (승리) 테스트"""
        from services.ranking_service import RankingService

        # 유저 생성
        user, _ = await user_repository.create("winner", "pass1234")

        # 게임 결과 업데이트
        service = RankingService(async_session)
        result = await service.update_game_result(
            user_id=user.id,
            is_winner=True,
            turn_count=25
        )

        assert result is not None
        assert result["score_before"] == 0
        assert result["score_after"] == 3.4  # 3 + 10/25
        assert result["new_rank"] == 1

    async def test_update_game_result_loss(
        self,
        user_repository: UserRepository,
        async_session
    ):
        """게임 결과 업데이트 (패배) 테스트"""
        from services.ranking_service import RankingService

        # 유저 생성 및 초기 점수 설정
        user, _ = await user_repository.create("loser", "pass1234")
        await user_repository.update_score(user.id, 5, True, 20)

        # 게임 결과 업데이트 (패배)
        service = RankingService(async_session)
        result = await service.update_game_result(
            user_id=user.id,
            is_winner=False,
            turn_count=30
        )

        assert result is not None
        assert result["score_before"] == 5
        assert result["score_after"] == 4  # 5 - 1
