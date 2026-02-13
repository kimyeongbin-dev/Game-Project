"""
API Endpoint Tests
FastAPI 엔드포인트 통합 테스트
"""

import pytest


# ==============================================
# 게임 생성 API 테스트
# ==============================================

class TestCreateGame:
    """게임 생성 API 테스트"""

    def test_create_game_default(self, client):
        """기본 게임 생성 (인증 필수)"""
        response = client.post("/api/v1/quoridor/games")

        assert response.status_code == 201
        data = response.json()
        assert "game_id" in data
        assert data["status"] == "in_progress"
        assert data["game_mode"] == "vs_ai"

    def test_create_game_vs_ai(self, client):
        """AI 대전 게임 생성"""
        response = client.post("/api/v1/quoridor/games", json={
            "ai_difficulty": "hard",
            "game_mode": "vs_ai"
        })

        assert response.status_code == 201
        data = response.json()
        assert data["game_mode"] == "vs_ai"

    def test_create_game_friend_match(self, client):
        """친구 대전 게임 생성"""
        response = client.post("/api/v1/quoridor/games", json={
            "game_mode": "friend_match"
        })

        assert response.status_code == 201
        data = response.json()
        assert data["game_mode"] == "friend_match"

    def test_create_game_without_auth(self, unauthenticated_client):
        """인증 없이 게임 생성 시도 - 401 반환"""
        response = unauthenticated_client.post("/api/v1/quoridor/games")
        assert response.status_code == 401


# ==============================================
# 게임 조회 API 테스트
# ==============================================

class TestGetGame:
    """게임 조회 API 테스트"""

    def test_get_game(self, client):
        """게임 상태 조회"""
        # 게임 생성
        create_response = client.post("/api/v1/quoridor/games")
        game_id = create_response.json()["game_id"]

        # 게임 조회
        response = client.get(f"/api/v1/quoridor/games/{game_id}")

        assert response.status_code == 200
        data = response.json()
        assert data["game_id"] == game_id
        assert "players" in data
        assert "walls" in data
        assert data["current_turn"] == 1

    def test_get_nonexistent_game(self, client):
        """존재하지 않는 게임 조회"""
        response = client.get("/api/v1/quoridor/games/fake-id-12345")

        assert response.status_code == 404


# ==============================================
# 폰 이동 API 테스트
# ==============================================

class TestMovePawn:
    """폰 이동 API 테스트"""

    def test_valid_move_forward(self, client):
        """유효한 전진 이동"""
        # 게임 생성
        create_response = client.post("/api/v1/quoridor/games")
        game_id = create_response.json()["game_id"]

        # Player 1 이동 (8,4) -> (7,4)
        response = client.post(f"/api/v1/quoridor/games/{game_id}/move", json={
            "row": 7,
            "col": 4
        })

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["game_state"]["players"]["player1"]["position"]["row"] == 7
        assert data["game_state"]["players"]["player1"]["position"]["col"] == 4

    def test_valid_move_sideways(self, client):
        """유효한 옆으로 이동"""
        create_response = client.post("/api/v1/quoridor/games")
        game_id = create_response.json()["game_id"]

        # Player 1 이동 (8,4) -> (8,3)
        response = client.post(f"/api/v1/quoridor/games/{game_id}/move", json={
            "row": 8,
            "col": 3
        })

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True

    def test_invalid_move_too_far(self, client):
        """무효한 이동 - 너무 멀리"""
        create_response = client.post("/api/v1/quoridor/games")
        game_id = create_response.json()["game_id"]

        # Player 1 이동 (8,4) -> (5,5) - 2칸 이상 이동 시도
        response = client.post(f"/api/v1/quoridor/games/{game_id}/move", json={
            "row": 5,
            "col": 5
        })

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is False
        assert "error" in data

    def test_move_nonexistent_game(self, client):
        """존재하지 않는 게임에서 이동"""
        response = client.post("/api/v1/quoridor/games/fake-id/move", json={
            "row": 7,
            "col": 4
        })

        assert response.status_code == 404


# ==============================================
# 벽 설치 API 테스트
# ==============================================

class TestPlaceWall:
    """벽 설치 API 테스트"""

    def test_valid_wall_horizontal(self, client):
        """유효한 수평 벽 설치"""
        create_response = client.post("/api/v1/quoridor/games")
        game_id = create_response.json()["game_id"]

        response = client.post(f"/api/v1/quoridor/games/{game_id}/wall", json={
            "row": 4,
            "col": 4,
            "orientation": "horizontal"
        })

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert len(data["game_state"]["walls"]) == 1

    def test_valid_wall_vertical(self, client):
        """유효한 수직 벽 설치"""
        create_response = client.post("/api/v1/quoridor/games")
        game_id = create_response.json()["game_id"]

        response = client.post(f"/api/v1/quoridor/games/{game_id}/wall", json={
            "row": 3,
            "col": 3,
            "orientation": "vertical"
        })

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True

    def test_invalid_wall_out_of_bounds(self, client):
        """범위 밖 벽 설치 - 422 Validation Error"""
        create_response = client.post("/api/v1/quoridor/games")
        game_id = create_response.json()["game_id"]

        response = client.post(f"/api/v1/quoridor/games/{game_id}/wall", json={
            "row": 10,
            "col": 10,
            "orientation": "horizontal"
        })

        assert response.status_code == 422

    def test_wall_decreases_remaining(self, client):
        """벽 설치 후 남은 벽 개수 감소"""
        create_response = client.post("/api/v1/quoridor/games")
        game_id = create_response.json()["game_id"]

        # 초기 벽 개수 확인
        game_response = client.get(f"/api/v1/quoridor/games/{game_id}")
        initial_walls = game_response.json()["players"]["player1"]["walls_remaining"]
        assert initial_walls == 10

        # 벽 설치
        client.post(f"/api/v1/quoridor/games/{game_id}/wall", json={
            "row": 4,
            "col": 4,
            "orientation": "horizontal"
        })

        # 벽 개수 감소 확인
        game_response = client.get(f"/api/v1/quoridor/games/{game_id}")
        remaining_walls = game_response.json()["players"]["player1"]["walls_remaining"]
        assert remaining_walls == 9


# ==============================================
# AI 이동 API 테스트
# ==============================================

class TestAIMove:
    """AI 이동 API 테스트"""

    def test_ai_move_after_player(self, client):
        """Player 이동 후 AI 이동"""
        create_response = client.post("/api/v1/quoridor/games", json={
            "game_mode": "vs_ai",
            "ai_difficulty": "normal"
        })
        game_id = create_response.json()["game_id"]

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
        assert data["action"]["type"] in ["move", "wall"]

    def test_ai_move_not_ai_turn(self, client):
        """Player 턴에 AI 이동 시도"""
        create_response = client.post("/api/v1/quoridor/games")
        game_id = create_response.json()["game_id"]

        # AI 이동 시도 (아직 Player 1 턴)
        response = client.post(f"/api/v1/quoridor/games/{game_id}/ai-move")

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is False

    def test_ai_move_game_continues(self, client):
        """AI 이동 후 게임 상태 유지"""
        create_response = client.post("/api/v1/quoridor/games")
        game_id = create_response.json()["game_id"]

        # Player 1 이동
        client.post(f"/api/v1/quoridor/games/{game_id}/move", json={
            "row": 7,
            "col": 4
        })

        # AI 이동
        client.post(f"/api/v1/quoridor/games/{game_id}/ai-move")

        # 게임 상태 확인 - Player 1 턴으로 복귀
        game_response = client.get(f"/api/v1/quoridor/games/{game_id}")
        data = game_response.json()
        assert data["current_turn"] == 1
        assert data["status"] == "in_progress"


# ==============================================
# 유효 이동 API 테스트
# ==============================================

class TestValidMoves:
    """유효 이동 API 테스트"""

    def test_get_valid_moves_initial(self, client):
        """초기 상태에서 유효 이동 목록"""
        create_response = client.post("/api/v1/quoridor/games")
        game_id = create_response.json()["game_id"]

        response = client.get(f"/api/v1/quoridor/games/{game_id}/valid-moves")

        assert response.status_code == 200
        data = response.json()
        assert "valid_pawn_moves" in data
        assert "valid_wall_placements" in data
        assert "walls_remaining" in data
        # 초기 위치 (8,4)에서 3개 이동 가능 (위, 좌, 우)
        assert len(data["valid_pawn_moves"]) == 3
        assert data["walls_remaining"] == 10

    def test_valid_wall_placements_count(self, client):
        """유효한 벽 설치 위치 개수"""
        create_response = client.post("/api/v1/quoridor/games")
        game_id = create_response.json()["game_id"]

        response = client.get(f"/api/v1/quoridor/games/{game_id}/valid-moves")
        data = response.json()

        # 초기 상태에서 많은 벽 설치 위치 가능
        assert len(data["valid_wall_placements"]) > 100


# ==============================================
# 게임 삭제 API 테스트
# ==============================================

class TestGameDeletion:
    """게임 삭제 API 테스트"""

    def test_abandon_game(self, client):
        """게임 포기"""
        create_response = client.post("/api/v1/quoridor/games")
        game_id = create_response.json()["game_id"]

        response = client.post(f"/api/v1/quoridor/games/{game_id}/abandon")

        assert response.status_code == 204

    def test_delete_game(self, client):
        """게임 삭제"""
        create_response = client.post("/api/v1/quoridor/games")
        game_id = create_response.json()["game_id"]

        response = client.delete(f"/api/v1/quoridor/games/{game_id}")

        assert response.status_code == 204

    def test_get_deleted_game(self, client):
        """삭제된 게임 조회 - 404"""
        create_response = client.post("/api/v1/quoridor/games")
        game_id = create_response.json()["game_id"]

        # 게임 삭제
        client.delete(f"/api/v1/quoridor/games/{game_id}")

        # 조회 시 404
        response = client.get(f"/api/v1/quoridor/games/{game_id}")
        assert response.status_code == 404


# ==============================================
# 세션 API 테스트
# ==============================================

class TestSessions:
    """세션 API 테스트"""

    def test_get_active_sessions_empty(self, client):
        """빈 활성 세션 목록"""
        response = client.get("/api/v1/quoridor/sessions")

        assert response.status_code == 200
        data = response.json()
        assert "sessions" in data
        assert "count" in data

    def test_get_active_sessions_with_game(self, client):
        """게임 생성 후 활성 세션 목록"""
        # 게임 생성
        client.post("/api/v1/quoridor/games")

        response = client.get("/api/v1/quoridor/sessions")

        assert response.status_code == 200
        data = response.json()
        assert data["count"] >= 1


# ==============================================
# 헬스 체크 API 테스트
# ==============================================

class TestHealthCheck:
    """헬스 체크 API 테스트"""

    def test_root(self, client):
        """루트 엔드포인트"""
        response = client.get("/")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"

    def test_health(self, client):
        """헬스 체크 엔드포인트"""
        response = client.get("/health")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
