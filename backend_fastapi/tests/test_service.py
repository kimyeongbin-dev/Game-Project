"""
QuoridorService Tests
서비스 레이어 테스트 (메모리 모드)
"""

import pytest
import sys
from pathlib import Path
from unittest.mock import patch, AsyncMock

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))
sys.path.insert(0, str(project_root.parent))

from services.quoridor_service import QuoridorService


@pytest.fixture
def service():
    """테스트용 서비스 인스턴스"""
    return QuoridorService()


@pytest.fixture
def mock_db_unavailable():
    """DB 비활성화 모킹"""
    with patch('services.quoridor_service.is_db_available', return_value=False):
        yield


@pytest.mark.asyncio
class TestGameCreation:
    """게임 생성 테스트"""

    async def test_create_vs_ai_game(self, service, mock_db_unavailable):
        """AI 대전 게임 생성"""
        game = await service.create_game(
            player1_name="TestPlayer",
            ai_difficulty="normal",
            game_mode="vs_ai"
        )

        assert game is not None
        assert game.player1.name == "TestPlayer"
        assert game.player2.name == "AI"
        assert game.game_mode.value == "vs_ai"
        assert game.game_id in service._games

    async def test_create_local_2p_game(self, service, mock_db_unavailable):
        """로컬 2인 게임 생성"""
        game = await service.create_game(
            player1_name="Player1",
            player2_name="Player2",
            game_mode="local_2p"
        )

        assert game.player1.name == "Player1"
        assert game.player2.name == "Player2"
        assert game.game_mode.value == "local_2p"

    async def test_ai_instance_created(self, service, mock_db_unavailable):
        """AI 인스턴스 생성 확인"""
        game = await service.create_game(game_mode="vs_ai")

        assert game.game_id in service._ai_instances
        assert game.game_id in service._ai_difficulties


@pytest.mark.asyncio
class TestGameRetrieval:
    """게임 조회 테스트"""

    async def test_get_existing_game(self, service, mock_db_unavailable):
        """존재하는 게임 조회"""
        game = await service.create_game()
        game_id = game.game_id

        retrieved = await service.get_game(game_id)

        assert retrieved is not None
        assert retrieved.game_id == game_id

    async def test_get_nonexistent_game(self, service, mock_db_unavailable):
        """존재하지 않는 게임 조회"""
        result = await service.get_game("nonexistent-id")

        assert result is None


@pytest.mark.asyncio
class TestPawnMovement:
    """폰 이동 테스트"""

    async def test_valid_move(self, service, mock_db_unavailable):
        """유효한 이동"""
        game = await service.create_game()
        game_id = game.game_id

        success, message, updated_game = await service.move_pawn(game_id, 7, 4)

        assert success is True
        assert updated_game.player1.position.row == 7
        assert updated_game.current_turn == 2

    async def test_invalid_move(self, service, mock_db_unavailable):
        """무효한 이동"""
        game = await service.create_game()
        game_id = game.game_id

        success, message, updated_game = await service.move_pawn(game_id, 5, 5)

        assert success is False
        assert updated_game is None

    async def test_move_nonexistent_game(self, service, mock_db_unavailable):
        """존재하지 않는 게임 이동"""
        success, message, game = await service.move_pawn("fake-id", 7, 4)

        assert success is False
        assert "not found" in message.lower()


@pytest.mark.asyncio
class TestWallPlacement:
    """벽 설치 테스트"""

    async def test_valid_wall(self, service, mock_db_unavailable):
        """유효한 벽 설치"""
        game = await service.create_game()
        game_id = game.game_id

        success, message, updated_game = await service.place_wall(
            game_id, 4, 4, "horizontal"
        )

        assert success is True
        assert len(updated_game.wall_manager.walls) == 1
        assert updated_game.player1.walls_remaining == 9

    async def test_invalid_wall_orientation(self, service, mock_db_unavailable):
        """잘못된 벽 방향"""
        game = await service.create_game()
        game_id = game.game_id

        success, message, updated_game = await service.place_wall(
            game_id, 4, 4, "invalid"
        )

        assert success is False


@pytest.mark.asyncio
class TestAIMove:
    """AI 이동 테스트"""

    async def test_ai_move_on_ai_turn(self, service, mock_db_unavailable):
        """AI 턴에 AI 이동"""
        game = await service.create_game(game_mode="vs_ai")
        game_id = game.game_id

        # Player 1 이동
        await service.move_pawn(game_id, 7, 4)

        # AI 턴
        success, message, action, updated_game = await service.ai_move(game_id)

        assert success is True
        assert action is not None
        assert updated_game.current_turn == 1  # 다시 Player 1 턴

    async def test_ai_move_not_ai_turn(self, service, mock_db_unavailable):
        """Player 턴에 AI 이동 시도"""
        game = await service.create_game(game_mode="vs_ai")
        game_id = game.game_id

        # Player 1 턴에 AI 이동 시도
        success, message, action, game = await service.ai_move(game_id)

        assert success is False
        assert "not ai's turn" in message.lower()


@pytest.mark.asyncio
class TestValidMoves:
    """유효 이동 조회 테스트"""

    async def test_get_valid_moves(self, service, mock_db_unavailable):
        """유효 이동 목록"""
        game = await service.create_game()
        game_id = game.game_id

        result = await service.get_valid_moves(game_id)

        assert result is not None
        assert "valid_pawn_moves" in result
        assert "valid_wall_placements" in result
        assert "walls_remaining" in result
        assert len(result["valid_pawn_moves"]) > 0


@pytest.mark.asyncio
class TestGameDeletion:
    """게임 삭제 테스트"""

    async def test_abandon_game(self, service, mock_db_unavailable):
        """게임 포기"""
        game = await service.create_game()
        game_id = game.game_id

        result = await service.abandon_game(game_id)

        assert result is True
        assert game_id not in service._games

    async def test_delete_game(self, service, mock_db_unavailable):
        """게임 삭제"""
        game = await service.create_game()
        game_id = game.game_id

        result = await service.delete_game(game_id)

        assert result is True
        assert game_id not in service._games
        assert game_id not in service._ai_instances


@pytest.mark.asyncio
class TestCacheManagement:
    """캐시 관리 테스트"""

    async def test_cache_cleanup(self, service, mock_db_unavailable):
        """캐시 정리"""
        # 여러 게임 생성
        for _ in range(5):
            await service.create_game()

        result = await service.cleanup_cache()

        assert "stale_removed" in result
        assert "limit_removed" in result
        assert "current_cache_size" in result

    async def test_access_time_updated(self, service, mock_db_unavailable):
        """액세스 시간 업데이트"""
        game = await service.create_game()
        game_id = game.game_id

        assert game_id in service._last_accessed

        # 다시 조회
        await service.get_game(game_id)

        assert game_id in service._last_accessed
