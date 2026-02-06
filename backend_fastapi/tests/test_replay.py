"""
Replay System Tests
리플레이 시스템 테스트
"""

import pytest
import uuid
import sys
from pathlib import Path

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))
sys.path.insert(0, str(project_root.parent))

from database.repository import GameSessionRepository


@pytest.mark.asyncio
class TestReplayMoves:
    """리플레이 수 기록 테스트"""

    async def test_add_initial_state(self, repository, sample_game_state):
        """초기 상태 저장 (step -1)"""
        game_id = str(uuid.uuid4())

        await repository.create(
            game_id=game_id,
            player1_name="Test",
            player2_name="AI",
            game_mode="vs_ai",
            ai_difficulty="normal",
            game_state=sample_game_state
        )

        # 초기 상태 저장
        move = await repository.add_move(
            game_id=game_id,
            step_no=-1,
            player=0,
            action_type="move",
            row=0,
            col=0,
            orientation=None,
            game_state_snapshot=sample_game_state
        )

        assert move.step_no == -1
        assert move.player == 0

    async def test_add_sequential_moves(self, repository, sample_game_state):
        """순차적 수 추가"""
        game_id = str(uuid.uuid4())

        await repository.create(
            game_id=game_id,
            player1_name="Test",
            player2_name="AI",
            game_mode="vs_ai",
            ai_difficulty="normal",
            game_state=sample_game_state
        )

        # 초기 상태
        await repository.add_move(
            game_id=game_id, step_no=-1, player=0,
            action_type="move", row=0, col=0,
            orientation=None, game_state_snapshot=sample_game_state
        )

        # Player 1 이동
        state1 = sample_game_state.copy()
        state1["current_turn"] = 2
        await repository.add_move(
            game_id=game_id, step_no=0, player=1,
            action_type="move", row=7, col=4,
            orientation=None, game_state_snapshot=state1
        )

        # Player 2 이동
        state2 = state1.copy()
        state2["current_turn"] = 1
        await repository.add_move(
            game_id=game_id, step_no=1, player=2,
            action_type="move", row=1, col=4,
            orientation=None, game_state_snapshot=state2
        )

        moves = await repository.get_moves(game_id)

        assert len(moves) == 3
        assert moves[0].step_no == -1
        assert moves[1].step_no == 0
        assert moves[2].step_no == 1

    async def test_get_state_at_initial(self, repository, sample_game_state):
        """초기 상태 조회"""
        game_id = str(uuid.uuid4())

        await repository.create(
            game_id=game_id,
            player1_name="Test",
            player2_name="AI",
            game_mode="vs_ai",
            ai_difficulty="normal",
            game_state=sample_game_state
        )

        await repository.add_move(
            game_id=game_id, step_no=-1, player=0,
            action_type="move", row=0, col=0,
            orientation=None, game_state_snapshot=sample_game_state
        )

        state = await repository.get_state_at_step(game_id, -1)

        assert state is not None
        assert state["current_turn"] == 1

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

        # Step 0 상태
        state0 = sample_game_state.copy()
        state0["turn_count"] = 1
        state0["current_turn"] = 2

        await repository.add_move(
            game_id=game_id, step_no=0, player=1,
            action_type="move", row=7, col=4,
            orientation=None, game_state_snapshot=state0
        )

        state = await repository.get_state_at_step(game_id, 0)

        assert state["turn_count"] == 1
        assert state["current_turn"] == 2


@pytest.mark.asyncio
class TestReplayWallMoves:
    """벽 설치 리플레이 테스트"""

    async def test_wall_move_record(self, repository, sample_game_state):
        """벽 설치 기록"""
        game_id = str(uuid.uuid4())

        await repository.create(
            game_id=game_id,
            player1_name="Test",
            player2_name="AI",
            game_mode="vs_ai",
            ai_difficulty="normal",
            game_state=sample_game_state
        )

        # 벽 설치 기록
        state_after_wall = sample_game_state.copy()
        state_after_wall["walls"] = [{"row": 4, "col": 4, "orientation": "horizontal"}]

        await repository.add_move(
            game_id=game_id, step_no=0, player=1,
            action_type="wall", row=4, col=4,
            orientation="horizontal", game_state_snapshot=state_after_wall
        )

        moves = await repository.get_moves(game_id)

        assert len(moves) == 1
        assert moves[0].action_type.value == "wall"
        assert moves[0].orientation == "horizontal"


@pytest.mark.asyncio
class TestDeleteMoves:
    """수 삭제 테스트"""

    async def test_delete_moves_after(self, repository, sample_game_state):
        """특정 스텝 이후 수 삭제"""
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
        for i in range(5):
            await repository.add_move(
                game_id=game_id, step_no=i, player=(i % 2) + 1,
                action_type="move", row=7-i, col=4,
                orientation=None, game_state_snapshot=sample_game_state
            )

        # Step 2 이후 삭제
        deleted = await repository.delete_moves_after(game_id, 2)

        assert deleted == 2  # step 3, 4 삭제

        moves = await repository.get_moves(game_id)
        assert len(moves) == 3  # step 0, 1, 2 남음

    async def test_delete_all_moves(self, repository, sample_game_state):
        """모든 수 삭제"""
        game_id = str(uuid.uuid4())

        await repository.create(
            game_id=game_id,
            player1_name="Test",
            player2_name="AI",
            game_mode="vs_ai",
            ai_difficulty="normal",
            game_state=sample_game_state
        )

        await repository.add_move(
            game_id=game_id, step_no=0, player=1,
            action_type="move", row=7, col=4,
            orientation=None, game_state_snapshot=sample_game_state
        )

        deleted = await repository.delete_moves_after(game_id, -1)

        assert deleted == 1
