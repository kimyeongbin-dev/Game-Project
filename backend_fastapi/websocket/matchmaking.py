"""
Matchmaking Queue
랭킹전 자동 매칭 시스템
"""

import logging
import asyncio
from typing import Optional, Dict, List, Tuple
from dataclasses import dataclass, field
from datetime import datetime
from collections import deque

logger = logging.getLogger(__name__)


@dataclass
class QueueEntry:
    """매칭 큐 항목"""
    user_id: int
    nickname: str
    score: float
    joined_at: datetime = field(default_factory=datetime.utcnow)


@dataclass
class MatchResult:
    """매칭 결과"""
    player1: QueueEntry
    player2: QueueEntry
    matched_at: datetime = field(default_factory=datetime.utcnow)


class MatchmakingQueue:
    """랭킹전 매칭 큐"""

    # 매칭 설정
    MATCH_CHECK_INTERVAL = 1.0      # 매칭 체크 간격 (초)
    SCORE_RANGE_INITIAL = 50        # 초기 점수 범위
    SCORE_RANGE_EXPAND_RATE = 10    # 대기 시간당 범위 확장
    SCORE_RANGE_MAX = 500           # 최대 점수 범위

    def __init__(self):
        self._queue: deque[QueueEntry] = deque()
        self._user_entries: Dict[int, QueueEntry] = {}  # user_id -> entry
        self._match_task: Optional[asyncio.Task] = None
        self._match_callback = None  # 매칭 완료 콜백
        self._running = False

    def set_match_callback(self, callback):
        """매칭 완료 시 호출할 콜백 설정"""
        self._match_callback = callback

    async def start(self):
        """매칭 서비스 시작"""
        if self._running:
            return
        self._running = True
        self._match_task = asyncio.create_task(self._match_loop())
        logger.info("Matchmaking queue started")

    async def stop(self):
        """매칭 서비스 중지"""
        self._running = False
        if self._match_task:
            self._match_task.cancel()
            try:
                await self._match_task
            except asyncio.CancelledError:
                pass
        logger.info("Matchmaking queue stopped")

    def join(self, user_id: int, nickname: str, score: float) -> int:
        """
        매칭 큐 참가

        Returns:
            현재 큐에서의 위치 (1부터 시작)
        """
        # 이미 큐에 있으면 무시
        if user_id in self._user_entries:
            return self._get_position(user_id)

        entry = QueueEntry(
            user_id=user_id,
            nickname=nickname,
            score=score
        )
        self._queue.append(entry)
        self._user_entries[user_id] = entry
        logger.info(f"Player joined queue: {nickname} (score={score})")
        return len(self._queue)

    def leave(self, user_id: int) -> bool:
        """매칭 큐 나가기"""
        if user_id not in self._user_entries:
            return False

        entry = self._user_entries.pop(user_id)
        self._queue = deque(e for e in self._queue if e.user_id != user_id)
        logger.info(f"Player left queue: {entry.nickname}")
        return True

    def is_in_queue(self, user_id: int) -> bool:
        """큐 참가 여부"""
        return user_id in self._user_entries

    def get_queue_status(self, user_id: int) -> dict:
        """큐 상태 조회"""
        position = self._get_position(user_id)
        return {
            "position": position,
            "waiting_count": len(self._queue),
            "estimated_wait": self._estimate_wait_time(position)
        }

    def _get_position(self, user_id: int) -> int:
        """큐에서의 위치 (1부터 시작)"""
        for i, entry in enumerate(self._queue):
            if entry.user_id == user_id:
                return i + 1
        return 0

    def _estimate_wait_time(self, position: int) -> Optional[int]:
        """예상 대기 시간 (초)"""
        if position <= 0:
            return None
        # 간단한 추정: 위치 * 5초
        return max(5, position * 5)

    async def _match_loop(self):
        """매칭 루프"""
        while self._running:
            try:
                await self._try_match()
                await asyncio.sleep(self.MATCH_CHECK_INTERVAL)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Match loop error: {e}")
                await asyncio.sleep(1)

    async def _try_match(self):
        """매칭 시도"""
        if len(self._queue) < 2:
            return

        # 큐를 리스트로 변환하여 매칭 시도
        queue_list = list(self._queue)
        matched_pairs: List[MatchResult] = []

        # 대기 시간이 긴 순서대로 매칭 시도
        queue_list.sort(key=lambda e: e.joined_at)

        matched_users = set()

        for i, entry1 in enumerate(queue_list):
            if entry1.user_id in matched_users:
                continue

            wait_seconds = (datetime.utcnow() - entry1.joined_at).total_seconds()
            score_range = min(
                self.SCORE_RANGE_INITIAL + (wait_seconds * self.SCORE_RANGE_EXPAND_RATE),
                self.SCORE_RANGE_MAX
            )

            # 가장 점수가 비슷한 상대 찾기
            best_match = None
            best_score_diff = float('inf')

            for j, entry2 in enumerate(queue_list):
                if i == j or entry2.user_id in matched_users:
                    continue

                score_diff = abs(entry1.score - entry2.score)
                if score_diff <= score_range and score_diff < best_score_diff:
                    best_match = entry2
                    best_score_diff = score_diff

            if best_match:
                matched_pairs.append(MatchResult(
                    player1=entry1,
                    player2=best_match
                ))
                matched_users.add(entry1.user_id)
                matched_users.add(best_match.user_id)
                logger.info(f"Match found: {entry1.nickname} vs {best_match.nickname}")

        # 매칭된 유저들 큐에서 제거 및 콜백 호출
        for match in matched_pairs:
            self.leave(match.player1.user_id)
            self.leave(match.player2.user_id)

            if self._match_callback:
                try:
                    await self._match_callback(match)
                except Exception as e:
                    logger.error(f"Match callback error: {e}")

    def get_stats(self) -> dict:
        """큐 통계"""
        return {
            "queue_size": len(self._queue),
            "running": self._running
        }


# 싱글톤 인스턴스
matchmaking_queue = MatchmakingQueue()
