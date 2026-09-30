"""
Matchmaking Queue Tests
매칭 시스템 테스트
"""

import pytest
import asyncio
from datetime import datetime, timedelta


class TestMatchmakingJoin:
    """매칭 큐 참가 테스트"""

    @pytest.mark.asyncio
    async def test_join_queue(self, matchmaking_queue, mock_user):
        """큐 참가 성공"""
        position = matchmaking_queue.join(
            mock_user.id, mock_user.nickname, mock_user.score
        )

        assert position == 1
        assert matchmaking_queue.is_in_queue(mock_user.id)

    @pytest.mark.asyncio
    async def test_join_queue_multiple(self, matchmaking_queue, mock_user, mock_user2):
        """여러 유저 큐 참가"""
        pos1 = matchmaking_queue.join(
            mock_user.id, mock_user.nickname, mock_user.score
        )
        pos2 = matchmaking_queue.join(
            mock_user2.id, mock_user2.nickname, mock_user2.score
        )

        assert pos1 == 1
        assert pos2 == 2

    @pytest.mark.asyncio
    async def test_join_queue_duplicate(self, matchmaking_queue, mock_user):
        """중복 참가 시 기존 위치 반환"""
        pos1 = matchmaking_queue.join(
            mock_user.id, mock_user.nickname, mock_user.score
        )
        pos2 = matchmaking_queue.join(
            mock_user.id, mock_user.nickname, mock_user.score
        )

        assert pos1 == pos2 == 1


class TestMatchmakingLeave:
    """매칭 큐 나가기 테스트"""

    @pytest.mark.asyncio
    async def test_leave_queue(self, matchmaking_queue, mock_user):
        """큐 나가기 성공"""
        matchmaking_queue.join(mock_user.id, mock_user.nickname, mock_user.score)

        result = matchmaking_queue.leave(mock_user.id)

        assert result is True
        assert matchmaking_queue.is_in_queue(mock_user.id) is False

    @pytest.mark.asyncio
    async def test_leave_queue_not_in_queue(self, matchmaking_queue):
        """큐에 없는 유저 나가기"""
        result = matchmaking_queue.leave(999)

        assert result is False


class TestMatchmakingStatus:
    """매칭 큐 상태 테스트"""

    @pytest.mark.asyncio
    async def test_get_queue_status(self, matchmaking_queue, mock_user):
        """큐 상태 조회"""
        matchmaking_queue.join(mock_user.id, mock_user.nickname, mock_user.score)

        status = matchmaking_queue.get_queue_status(mock_user.id)

        assert status["position"] == 1
        assert status["waiting_count"] == 1
        assert status["estimated_wait"] is not None

    @pytest.mark.asyncio
    async def test_get_queue_status_not_in_queue(self, matchmaking_queue):
        """큐에 없는 유저 상태 조회"""
        status = matchmaking_queue.get_queue_status(999)

        assert status["position"] == 0


class TestMatchmakingMatch:
    """매칭 로직 테스트"""

    @pytest.mark.asyncio
    async def test_match_similar_score(self, matchmaking_queue_stopped, mock_user, mock_user2):
        """비슷한 점수 매칭"""
        matched = []

        async def on_match(match_result):
            matched.append(match_result)

        matchmaking_queue_stopped.set_match_callback(on_match)

        # 비슷한 점수 유저 추가
        matchmaking_queue_stopped.join(mock_user.id, mock_user.nickname, 10.0)
        matchmaking_queue_stopped.join(mock_user2.id, mock_user2.nickname, 15.0)

        # 수동으로 매칭 시도
        await matchmaking_queue_stopped._try_match()

        assert len(matched) == 1
        assert matched[0].player1.user_id in [mock_user.id, mock_user2.id]
        assert matched[0].player2.user_id in [mock_user.id, mock_user2.id]

    @pytest.mark.asyncio
    async def test_match_no_match_different_score(self, matchmaking_queue_stopped, mock_user, mock_user2):
        """점수 차이가 큰 경우 매칭 안됨 (초기)"""
        matched = []

        async def on_match(match_result):
            matched.append(match_result)

        matchmaking_queue_stopped.set_match_callback(on_match)

        # 점수 차이가 큰 유저 추가 (초기 범위: 50)
        matchmaking_queue_stopped.join(mock_user.id, mock_user.nickname, 10.0)
        matchmaking_queue_stopped.join(mock_user2.id, mock_user2.nickname, 100.0)

        # 수동으로 매칭 시도
        await matchmaking_queue_stopped._try_match()

        # 점수 차이가 커서 초기에는 매칭 안됨
        assert len(matched) == 0

    @pytest.mark.asyncio
    async def test_match_not_enough_players(self, matchmaking_queue_stopped, mock_user):
        """플레이어 1명이면 매칭 안됨"""
        matched = []

        async def on_match(match_result):
            matched.append(match_result)

        matchmaking_queue_stopped.set_match_callback(on_match)
        matchmaking_queue_stopped.join(mock_user.id, mock_user.nickname, 10.0)

        await matchmaking_queue_stopped._try_match()

        assert len(matched) == 0


class TestMatchmakingService:
    """매칭 서비스 시작/종료 테스트"""

    @pytest.mark.asyncio
    async def test_start_and_stop(self, matchmaking_queue_stopped):
        """서비스 시작 및 종료"""
        assert matchmaking_queue_stopped._running is False

        await matchmaking_queue_stopped.start()
        assert matchmaking_queue_stopped._running is True
        assert matchmaking_queue_stopped._match_task is not None

        await matchmaking_queue_stopped.stop()
        assert matchmaking_queue_stopped._running is False

    @pytest.mark.asyncio
    async def test_double_start(self, matchmaking_queue_stopped):
        """중복 시작 시 무시"""
        await matchmaking_queue_stopped.start()
        task1 = matchmaking_queue_stopped._match_task

        await matchmaking_queue_stopped.start()
        task2 = matchmaking_queue_stopped._match_task

        assert task1 is task2

        await matchmaking_queue_stopped.stop()


class TestMatchmakingStats:
    """통계 테스트"""

    @pytest.mark.asyncio
    async def test_get_stats(self, matchmaking_queue, mock_user):
        """통계 조회"""
        matchmaking_queue.join(mock_user.id, mock_user.nickname, mock_user.score)

        stats = matchmaking_queue.get_stats()

        assert stats["queue_size"] == 1
        assert stats["running"] is True
