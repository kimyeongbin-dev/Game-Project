"""
API Endpoint Tests
FastAPI 엔드포인트 통합 테스트
"""

import pytest
import sys
from pathlib import Path
from unittest.mock import patch

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))
sys.path.insert(0, str(project_root.parent))

from fastapi.testclient import TestClient
from main import app


@pytest.fixture
def client():
    """테스트 클라이언트"""
    with patch('services.quoridor_service.is_db_available', return_value=False):
        with TestClient(app) as c:
            yield c


@pytest.fixture
def game_id(client):
    """테스트용 게임 생성"""
    response = client.post("/api/v1/quoridor/games", json={
        "player1_name": "TestPlayer",
        "ai_difficulty": "normal",
        "game_mode": "vs_ai"
    })
    return response.json()["game_id"]


class TestCreateGame:
    """게임 생성 API 테스트"""

    def test_create_game_default(self, client):
        """기본 게임 생성"""
        response = client.post("/api/v1/quoridor/games")

        assert response.status_code == 201
        data = response.json()
        assert "game_id" in data
        assert data["status"] == "in_progress"
        assert data["game_mode"] == "vs_ai"

    def test_create_game_custom(self, client):
        """커스텀 설정 게임 생성"""
        response = client.post("/api/v1/quoridor/games", json={
            "player1_name": "Alice",
            "player2_name": "Bob",
            "game_mode": "local_2p"
        })

        assert response.status_code == 201
        data = response.json()
        assert data["game_mode"] == "local_2p"


class TestGetGame:
    """게임 조회 API 테스트"""

    def test_get_game(self, client, game_id):
        """게임 상태 조회"""
        response = client.get(f"/api/v1/quoridor/games/{game_id}")

        assert response.status_code == 200
        data = response.json()
        assert data["game_id"] == game_id
        assert "players" in data
        assert "walls" in data

    def test_get_nonexistent_game(self, client):
        """존재하지 않는 게임 조회"""
        response = client.get("/api/v1/quoridor/games/fake-id")

        assert response.status_code == 404


class TestMovePawn:
    """폰 이동 API 테스트"""

    def test_valid_move(self, client, game_id):
        """유효한 이동"""
        response = client.post(f"/api/v1/quoridor/games/{game_id}/move", json={
            "row": 7,
            "col": 4
        })

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["game_state"]["players"]["player1"]["position"]["row"] == 7

    def test_invalid_move(self, client, game_id):
        """무효한 이동"""
        response = client.post(f"/api/v1/quoridor/games/{game_id}/move", json={
            "row": 5,
            "col": 5
        })

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is False
        assert "error" in data


class TestPlaceWall:
    """벽 설치 API 테스트"""

    def test_valid_wall(self, client, game_id):
        """유효한 벽 설치"""
        response = client.post(f"/api/v1/quoridor/games/{game_id}/wall", json={
            "row": 4,
            "col": 4,
            "orientation": "horizontal"
        })

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert len(data["game_state"]["walls"]) == 1

    def test_invalid_wall_position(self, client, game_id):
        """범위 밖 벽 설치"""
        response = client.post(f"/api/v1/quoridor/games/{game_id}/wall", json={
            "row": 10,
            "col": 10,
            "orientation": "horizontal"
        })

        # 422: Validation Error
        assert response.status_code == 422


class TestAIMove:
    """AI 이동 API 테스트"""

    def test_ai_move(self, client, game_id):
        """AI 이동"""
        # Player 1 이동
        client.post(f"/api/v1/quoridor/games/{game_id}/move", json={
            "row": 7,
            "col": 4
        })

        # AI 이동
        response = client.post(f"/api/v1/quoridor/games/{game_id}/ai-move")

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert "action" in data

    def test_ai_move_not_ai_turn(self, client, game_id):
        """Player 턴에 AI 이동"""
        response = client.post(f"/api/v1/quoridor/games/{game_id}/ai-move")

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is False


class TestValidMoves:
    """유효 이동 API 테스트"""

    def test_get_valid_moves(self, client, game_id):
        """유효 이동 목록"""
        response = client.get(f"/api/v1/quoridor/games/{game_id}/valid-moves")

        assert response.status_code == 200
        data = response.json()
        assert "valid_pawn_moves" in data
        assert "valid_wall_placements" in data
        assert "walls_remaining" in data


class TestGameDeletion:
    """게임 삭제 API 테스트"""

    def test_abandon_game(self, client, game_id):
        """게임 포기"""
        response = client.post(f"/api/v1/quoridor/games/{game_id}/abandon")

        assert response.status_code == 204

    def test_delete_game(self, client, game_id):
        """게임 삭제"""
        response = client.delete(f"/api/v1/quoridor/games/{game_id}")

        assert response.status_code == 204


class TestSessions:
    """세션 API 테스트"""

    def test_get_active_sessions(self, client, game_id):
        """활성 세션 목록"""
        response = client.get("/api/v1/quoridor/sessions")

        assert response.status_code == 200
        data = response.json()
        assert "sessions" in data
        assert "count" in data
