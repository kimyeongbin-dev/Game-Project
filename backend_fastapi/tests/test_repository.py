"""
Repository Tests
DB CRUD 작업 테스트
"""

import pytest
import uuid

from database.repository import GameSessionRepository
from database.models import GameStatus, GameMode


@pytest.mark.asyncio
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


@pytest.mark.asyncio
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


@pytest.mark.asyncio
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


@pytest.mark.asyncio
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


@pytest.mark.asyncio
class TestGameMoves:
    """GameMove 테스트"""

    async def test_add_move(self, repository, sample_game_state):
        """수 추가"""
        game_id = str(uuid.uuid4())

        await repository.create(
            game_id=game_id,
            player1_name="Test",
            player2_name="AI",
            game_mode="vs_ai",
            ai_difficulty="normal",
            game_state=sample_game_state
        )

        move = await repository.add_move(
            game_id=game_id,
            step_no=0,
            player=1,
            action_type="move",
            row=7,
            col=4,
            orientation=None,
            game_state_snapshot=sample_game_state
        )

        assert move is not None
        assert move.step_no == 0
        assert move.player == 1

    async def test_get_moves(self, repository, sample_game_state):
        """수 목록 조회"""
        game_id = str(uuid.uuid4())

        await repository.create(
            game_id=game_id,
            player1_name="Test",
            player2_name="AI",
            game_mode="vs_ai",
            ai_difficulty="normal",
            game_state=sample_game_state
        )

        # 여러 수 추가
        for i in range(3):
            await repository.add_move(
                game_id=game_id,
                step_no=i,
                player=(i % 2) + 1,
                action_type="move",
                row=7 - i,
                col=4,
                orientation=None,
                game_state_snapshot=sample_game_state
            )

        moves = await repository.get_moves(game_id)

        assert len(moves) == 3
        assert moves[0].step_no == 0
        assert moves[2].step_no == 2

    async def test_get_total_moves(self, repository, sample_game_state):
        """총 수 개수"""
        game_id = str(uuid.uuid4())

        await repository.create(
            game_id=game_id,
            player1_name="Test",
            player2_name="AI",
            game_mode="vs_ai",
            ai_difficulty="normal",
            game_state=sample_game_state
        )

        # 초기 상태 (step -1) + 2개 수
        await repository.add_move(
            game_id=game_id,
            step_no=-1,
            player=0,
            action_type="move",
            row=0,
            col=0,
            orientation=None,
            game_state_snapshot=sample_game_state
        )

        await repository.add_move(
            game_id=game_id,
            step_no=0,
            player=1,
            action_type="move",
            row=7,
            col=4,
            orientation=None,
            game_state_snapshot=sample_game_state
        )

        await repository.add_move(
            game_id=game_id,
            step_no=1,
            player=2,
            action_type="move",
            row=1,
            col=4,
            orientation=None,
            game_state_snapshot=sample_game_state
        )

        total = await repository.get_total_moves(game_id)

        # step >= 0 만 카운트 (초기 상태 제외)
        assert total == 2

    async def test_get_state_at_step(self, repository, sample_game_state):
        """특정 스텝 상태 조회"""
        game_id = str(uuid.uuid4())

        await repository.create(
            game_id=game_id,
            player1_name="Test",
            player2_name="AI",
            game_mode="vs_ai",
            ai_difficulty="normal",
            game_state=sample_game_state
        )

        # 특정 상태로 수 추가
        step1_state = sample_game_state.copy()
        step1_state["turn_count"] = 1

        await repository.add_move(
            game_id=game_id,
            step_no=0,
            player=1,
            action_type="move",
            row=7,
            col=4,
            orientation=None,
            game_state_snapshot=step1_state
        )

        state = await repository.get_state_at_step(game_id, 0)

        assert state is not None
        assert state["turn_count"] == 1
