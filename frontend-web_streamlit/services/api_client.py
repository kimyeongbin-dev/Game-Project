"""
API Client
백엔드 API 통신 클라이언트
"""

import requests
from typing import Optional
from dataclasses import dataclass


@dataclass
class APIConfig:
    """API 설정"""
    base_url: str = "http://localhost:8000"
    timeout: int = 10


class QuoridorAPIClient:
    """쿼리도 API 클라이언트"""

    def __init__(self, config: Optional[APIConfig] = None):
        self.config = config or APIConfig()
        self.base_url = f"{self.config.base_url}/api/v1/quoridor"

    def create_game(
        self,
        player_name: str = "Player",
        ai_difficulty: str = "normal"
    ) -> dict:
        """새 게임 생성"""
        response = requests.post(
            f"{self.base_url}/games",
            json={
                "player_name": player_name,
                "ai_difficulty": ai_difficulty
            },
            timeout=self.config.timeout
        )
        response.raise_for_status()
        return response.json()

    def get_game(self, game_id: str) -> dict:
        """게임 상태 조회"""
        response = requests.get(
            f"{self.base_url}/games/{game_id}",
            timeout=self.config.timeout
        )
        response.raise_for_status()
        return response.json()

    def move_pawn(self, game_id: str, row: int, col: int) -> dict:
        """폰 이동"""
        response = requests.post(
            f"{self.base_url}/games/{game_id}/move",
            json={"row": row, "col": col},
            timeout=self.config.timeout
        )
        response.raise_for_status()
        return response.json()

    def place_wall(
        self,
        game_id: str,
        row: int,
        col: int,
        orientation: str
    ) -> dict:
        """벽 설치"""
        response = requests.post(
            f"{self.base_url}/games/{game_id}/wall",
            json={
                "row": row,
                "col": col,
                "orientation": orientation
            },
            timeout=self.config.timeout
        )
        response.raise_for_status()
        return response.json()

    def ai_move(self, game_id: str) -> dict:
        """AI 턴 요청"""
        response = requests.post(
            f"{self.base_url}/games/{game_id}/ai-move",
            timeout=self.config.timeout
        )
        response.raise_for_status()
        return response.json()

    def get_valid_moves(self, game_id: str) -> dict:
        """유효한 이동 목록 조회"""
        response = requests.get(
            f"{self.base_url}/games/{game_id}/valid-moves",
            timeout=self.config.timeout
        )
        response.raise_for_status()
        return response.json()

    def delete_game(self, game_id: str) -> bool:
        """게임 삭제"""
        response = requests.delete(
            f"{self.base_url}/games/{game_id}",
            timeout=self.config.timeout
        )
        return response.status_code == 204


# 기본 클라이언트 인스턴스
api_client = QuoridorAPIClient()
