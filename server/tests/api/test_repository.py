"""
Repository Tests
DB CRUD 작업 테스트
"""

import pytest
import uuid

from app.db.repository import GameSessionRepository
from app.db.models import GameStatus, GameMode


class TestGameSessionCreate:
    """게임 세션 생성 테스트"""

    async def test_create_game_session(self, repository, sample_game_state):
        """게임 세션 생성"""
        game_id = str(uuid.uuid4())

        session = await repository.create(
            game_id=game_id,
            player1_name="Test Player",
            player2_name="AI",
            game_mode="vs_ai",
            ai_difficulty="normal",
            game_state=sample_game_state
        )

        assert session is not None
        assert session.game_id == game_id
        assert session.player1_name == "Test Player"
        assert session.player2_name == "AI"
        assert session.status == GameStatus.IN_PROGRESS

    async def test_create_local_2p_game(self, repository, sample_game_state):
        """로컬 2인 게임 생성"""
        game_id = str(uuid.uuid4())

        session = await repository.create(
            game_id=game_id,
            player1_name="Player 1",
            player2_name="Player 2",
            game_mode="local_2p",
            ai_difficulty=None,
            game_state=sample_game_state
        )

        assert session.game_mode == GameMode.LOCAL_2P
        assert session.ai_difficulty is None


class TestGameSessionRead:
    """게임 세션 조회 테스트"""

    async def test_get_by_id(self, repository, sample_game_state):
        """ID로 조회"""
        game_id = str(uuid.uuid4())

        # 생성
        await repository.create(
            game_id=game_id,
            player1_name="Test",
            player2_name="AI",
            game_mode="vs_ai",
            ai_difficulty="normal",
            game_state=sample_game_state
        )

        # 조회
        session = await repository.get_by_id(game_id)

        assert session is not None
        assert session.game_id == game_id

    async def test_get_nonexistent_game(self, repository):
        """존재하지 않는 게임 조회"""
        session = await repository.get_by_id("nonexistent-id")

        assert session is None

    async def test_get_active_sessions(self, repository, sample_game_state):
        """진행 중인 세션 목록"""
        # 여러 게임 생성
        for i in range(3):
            await repository.create(
                game_id=str(uuid.uuid4()),
                player1_name=f"Player {i}",
                player2_name="AI",
                game_mode="vs_ai",
                ai_difficulty="normal",
                game_state=sample_game_state
            )

        sessions = await repository.get_active_sessions(limit=10)

        assert len(sessions) == 3


class TestGameSessionUpdate:
    """게임 세션 업데이트 테스트"""

    async def test_update_game_state(self, repository, sample_game_state):
        """게임 상태 업데이트"""
        game_id = str(uuid.uuid4())

        await repository.create(
            game_id=game_id,
            player1_name="Test",
            player2_name="AI",
            game_mode="vs_ai",
            ai_difficulty="normal",
            game_state=sample_game_state
        )

        # 상태 업데이트
        updated_state = sample_game_state.copy()
        updated_state["current_turn"] = 2
        updated_state["turn_count"] = 1

        session = await repository.update_game_state(
            game_id=game_id,
            game_state=updated_state
        )

        assert session.current_turn == 2
        assert session.turn_count == 1

    async def test_update_with_winner(self, repository, sample_game_state):
        """승자 업데이트"""
        game_id = str(uuid.uuid4())

        await repository.create(
            game_id=game_id,
            player1_name="Test",
            player2_name="AI",
            game_mode="vs_ai",
            ai_difficulty="normal",
            game_state=sample_game_state
        )

        session = await repository.update_game_state(
            game_id=game_id,
            game_state=sample_game_state,
            status="player1_win",
            winner=1
        )

        assert session.status == GameStatus.PLAYER1_WIN
        assert session.winner == 1


class TestGameSessionDelete:
    """게임 세션 삭제 테스트"""

    async def test_abandon_game(self, repository, sample_game_state):
        """게임 포기"""
        game_id = str(uuid.uuid4())

        await repository.create(
            game_id=game_id,
            player1_name="Test",
            player2_name="AI",
            game_mode="vs_ai",
            ai_difficulty="normal",
            game_state=sample_game_state
        )

        result = await repository.abandon_game(game_id)

        assert result is True

        session = await repository.get_by_id(game_id)
        assert session.status == GameStatus.ABANDONED

    async def test_hard_delete(self, repository, sample_game_state):
        """완전 삭제"""
        game_id = str(uuid.uuid4())

        await repository.create(
            game_id=game_id,
            player1_name="Test",
            player2_name="AI",
            game_mode="vs_ai",
            ai_difficulty="normal",
            game_state=sample_game_state
        )

        result = await repository.hard_delete(game_id)

        assert result is True

        # 삭제된 게임은 조회 불가 (is_deleted=True)
        session = await repository.get_by_id(game_id)
        assert session is None


