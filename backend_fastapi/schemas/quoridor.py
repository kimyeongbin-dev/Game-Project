"""
Quoridor API Schemas
Pydantic 모델 정의
"""

from typing import Optional, Literal
from pydantic import BaseModel, Field


class PositionSchema(BaseModel):
    """위치 스키마"""
    row: int = Field(..., ge=0, le=8, description="행 좌표 (0-8)")
    col: int = Field(..., ge=0, le=8, description="열 좌표 (0-8)")


class WallSchema(BaseModel):
    """벽 스키마"""
    row: int = Field(..., ge=0, le=7, description="벽 시작 행 (0-7)")
    col: int = Field(..., ge=0, le=7, description="벽 시작 열 (0-7)")
    orientation: Literal["horizontal", "vertical"] = Field(..., description="벽 방향")


class PlayerSchema(BaseModel):
    """플레이어 스키마"""
    name: str
    position: PositionSchema
    walls_remaining: int = Field(..., ge=0, le=10)
    goal_row: int = Field(..., ge=0, le=8)


class PlayersSchema(BaseModel):
    """플레이어들 스키마"""
    player1: PlayerSchema
    player2: PlayerSchema


class GameStateSchema(BaseModel):
    """게임 상태 스키마"""
    game_id: str
    status: Literal["in_progress", "finished"]
    current_turn: int = Field(..., ge=1, le=2)
    turn_count: int = Field(..., ge=0)
    players: PlayersSchema
    walls: list[WallSchema]
    winner: Optional[int] = Field(None, ge=1, le=2)
    created_at: str
    updated_at: str


# Request Schemas

class CreateGameRequest(BaseModel):
    """게임 생성 요청"""
    player_name: str = Field(default="Player", max_length=50)
    ai_difficulty: Literal["easy", "normal", "hard"] = Field(default="normal")


class MoveRequest(BaseModel):
    """폰 이동 요청"""
    row: int = Field(..., ge=0, le=8, description="목표 행")
    col: int = Field(..., ge=0, le=8, description="목표 열")


class WallRequest(BaseModel):
    """벽 설치 요청"""
    row: int = Field(..., ge=0, le=7, description="벽 시작 행")
    col: int = Field(..., ge=0, le=7, description="벽 시작 열")
    orientation: Literal["horizontal", "vertical"] = Field(..., description="벽 방향")


# Response Schemas

class CreateGameResponse(BaseModel):
    """게임 생성 응답"""
    game_id: str
    status: str
    current_turn: int
    message: str


class ActionResponse(BaseModel):
    """액션 응답 (이동/벽 설치)"""
    success: bool
    game_state: Optional[GameStateSchema] = None
    message: str
    error: Optional[str] = None


class AIActionSchema(BaseModel):
    """AI 액션 정보"""
    type: Literal["move", "wall"]
    row: int
    col: int
    orientation: Optional[Literal["horizontal", "vertical"]] = None


class AIActionResponse(BaseModel):
    """AI 액션 응답"""
    success: bool
    action: Optional[AIActionSchema] = None
    game_state: Optional[GameStateSchema] = None
    message: str
    error: Optional[str] = None


class ValidMovesResponse(BaseModel):
    """유효한 이동 목록 응답"""
    valid_pawn_moves: list[PositionSchema]
    valid_wall_placements: list[WallSchema]
    walls_remaining: int


class ErrorResponse(BaseModel):
    """에러 응답"""
    success: bool = False
    error: str
    message: str
