"""
Daily Reset Scheduler
매일 KST 09:00 (UTC 00:00) 리셋 작업
"""

import logging
from datetime import datetime, timezone, timedelta, date
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from app.db.config import get_session_factory, is_db_available
from app.db.repository import UserRepository, RankingRepository

logger = logging.getLogger(__name__)

# KST = UTC+9
KST = timezone(timedelta(hours=9))

# 스케줄러 인스턴스.
#
# AsyncIOScheduler.start() 는 호출 시점의 실행 중인 이벤트 루프에 바인딩되며,
# shutdown() 한 인스턴스를 다른 루프에서 재시작할 수 없다.
# 모듈 레벨 싱글톤으로 두면 lifespan 이 여러 번 실행되는 환경(TestClient 등)에서
# 두 번째 실행부터 "RuntimeError: Event loop is closed" 가 발생한다.
# 따라서 인스턴스는 setup_scheduler() 에서 매번 새로 생성한다.
_scheduler: AsyncIOScheduler | None = None


async def daily_reset_job():
    """
    일일 리셋 작업
    - KST 09:00 (UTC 00:00)에 실행

    리셋 프로세스:
    1. 현재 1위 유저 조회
    2. DailyChampion 테이블에 1위 정보 저장
    3. 게임 중이 아닌 유저 전체 삭제
    4. 1위 유저만 유지 (stats 리셋)
    """
    logger.info("=== Daily Reset Started ===")
    reset_time = datetime.now(KST)
    logger.info(f"Reset time (KST): {reset_time.strftime('%Y-%m-%d %H:%M:%S')}")

    if not is_db_available():
        logger.warning("Database not available, skipping daily reset")
        return

    session_factory = get_session_factory()
    if not session_factory:
        logger.warning("Session factory not available, skipping daily reset")
        return

    async with session_factory() as session:
        try:
            user_repo = UserRepository(session)
            ranking_repo = RankingRepository(session)

            # 1. 현재 1위 유저 조회
            champion = await ranking_repo.get_top_user()

            if champion:
                logger.info(f"Current Champion: {champion.nickname} (Score: {champion.score}, Wins: {champion.wins})")

                # 2. DailyChampion 테이블에 저장
                # 오늘 날짜 (KST 기준) - 리셋 전날의 챔피언
                yesterday = (reset_time - timedelta(days=1)).date()
                await ranking_repo.save_daily_champion(
                    nickname=champion.nickname,
                    score=champion.score,
                    wins=champion.wins,
                    losses=champion.losses,
                    best_turn_count=champion.best_turn_count,
                    champion_date=yesterday,
                    preserved_user_id=champion.id
                )
                logger.info(f"Champion saved for date: {yesterday}")

                # 3. 게임 중이 아닌 유저 삭제 (1위 제외)
                deleted_count = await user_repo.delete_inactive_users(
                    exclude_user_id=champion.id
                )
                logger.info(f"Deleted {deleted_count} inactive users")

                # 4. 1위 유저 stats 리셋 (점수, 승패 초기화)
                await user_repo.reset_stats(champion.id)
                logger.info(f"Champion {champion.nickname} stats reset for new day")

            else:
                logger.info("No users found, cleaning up...")
                # 유저가 없으면 전체 삭제
                deleted_count = await user_repo.delete_all_users()
                logger.info(f"Deleted {deleted_count} users (no champion)")

            logger.info("=== Daily Reset Completed ===")

        except Exception as e:
            logger.error(f"Daily reset failed: {e}")
            raise


async def manual_reset():
    """
    수동 리셋 (테스트용)
    """
    logger.info("Manual reset triggered")
    await daily_reset_job()


def setup_scheduler() -> None:
    """
    스케줄러 설정 및 시작
    - KST 09:00 = UTC 00:00

    현재 이벤트 루프에 바인딩된 새 인스턴스를 생성한다. 이미 동작 중이면 무시한다.
    """
    global _scheduler

    if _scheduler is not None and _scheduler.running:
        logger.debug("Scheduler already running, skipping setup")
        return

    _scheduler = AsyncIOScheduler()

    # 일일 리셋 작업 등록
    _scheduler.add_job(
        daily_reset_job,
        CronTrigger(hour=0, minute=0, timezone='UTC'),  # UTC 00:00 = KST 09:00
        id='daily_reset',
        replace_existing=True,
        name='Daily Reset (KST 09:00)'
    )

    _scheduler.start()
    logger.info("Daily reset scheduler started (runs at KST 09:00 / UTC 00:00)")


def shutdown_scheduler() -> None:
    """
    스케줄러 종료

    인스턴스 참조까지 해제하여 다음 lifespan 이 새 루프에 새로 바인딩할 수 있게 한다.
    """
    global _scheduler

    if _scheduler is None:
        return

    if _scheduler.running:
        _scheduler.shutdown()
        logger.info("Scheduler shutdown complete")

    _scheduler = None


def get_next_reset_time() -> datetime:
    """
    다음 리셋 시간 반환 (KST 기준)
    """
    now_kst = datetime.now(KST)
    next_reset = now_kst.replace(hour=9, minute=0, second=0, microsecond=0)

    if now_kst >= next_reset:
        next_reset += timedelta(days=1)

    return next_reset


def get_time_until_reset() -> timedelta:
    """
    리셋까지 남은 시간 반환
    """
    return get_next_reset_time() - datetime.now(KST)
