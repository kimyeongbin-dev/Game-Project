"""
Quoridor API Router
쿼리도 게임 REST API 엔드포인트
"""

from fastapi import APIRouter, HTTPException, status, Query

from schemas.quoridor import (
    CreateGameRequest,
    CreateGameResponse,
    MoveRequest,
    WallRequest,
    ActionResponse,
    AIActionResponse,
    ValidMovesResponse,
    GameStateSchema,
    ErrorResponse,
    ActiveSessionsResponse,
    GameHistoryResponse,
    ReplayMovesResponse,
    ReplayStateResponse,
)
from services.quoridor_service import quoridor_service

router = APIRouter(
    prefix="/api/v1/quoridor",
    tags=["quoridor"],
)


@router.get(
    "/sessions",
    response_model=ActiveSessionsResponse,
    summary="진행 중인 게임 세션 목록",
    description="DB에 저장된 진행 중인 게임 세션 목록을 조회합니다.",
)
async def get_active_sessions(limit: int = Query(default=50, ge=1, le=100)):
    """진행 중인 게임 세션 목록 조회"""
    sessions = await quoridor_service.get_active_sessions(limit=limit)
    return ActiveSessionsResponse(sessions=sessions, count=len(sessions))


@router.post(
    "/games",
    response_model=CreateGameResponse,
    status_code=status.HTTP_201_CREATED,
    summary="새 게임 생성",
    description="새로운 쿼리도 게임을 생성합니다.",
)
async def create_game(request: CreateGameRequest = CreateGameRequest()):
    """새 게임 생성"""
    game = await quoridor_service.create_game(
        player1_name=request.player1_name,
        player2_name=request.player2_name,
        ai_difficulty=request.ai_difficulty,
        game_mode=request.game_mode
    )

    return CreateGameResponse(
        game_id=game.game_id,
        status=game.status.value,
        game_mode=game.game_mode.value,
        current_turn=game.current_turn,
        message="Game created successfully"
    )


@router.get(
    "/games/{game_id}",
    response_model=GameStateSchema,
    summary="게임 상태 조회",
    description="현재 게임 상태를 조회합니다. 메모리에 없으면 DB에서 자동 복구합니다.",
)
async def get_game(game_id: str):
    """게임 상태 조회"""
    game = await quoridor_service.get_game(game_id)
    if not game:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "game_not_found", "message": "Game not found"}
        )

    return game.to_dict()


@router.post(
    "/games/{game_id}/recover",
    response_model=GameStateSchema,
    summary="게임 복구",
    description="DB에서 게임을 복구하여 메모리에 로드합니다.",
)
async def recover_game(game_id: str):
    """DB에서 게임 복구"""
    game = await quoridor_service.recover_game(game_id)
    if not game:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "game_not_found", "message": "Game not found in database"}
        )

    return game.to_dict()


@router.get(
    "/games/{game_id}/history",
    response_model=GameHistoryResponse,
    summary="게임 히스토리 조회",
    description="리플레이를 위한 게임의 모든 수 기록을 조회합니다.",
)
async def get_game_history(game_id: str):
    """게임 히스토리 조회"""
    history = await quoridor_service.get_game_history(game_id)
    if history is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "game_not_found", "message": "Game not found"}
        )

    return GameHistoryResponse(game_id=game_id, history=history, total_moves=len(history))


@router.post(
    "/games/{game_id}/move",
    response_model=ActionResponse,
    summary="폰 이동",
    description="현재 턴 플레이어의 폰을 이동합니다.",
)
async def move_pawn(game_id: str, request: MoveRequest):
    """폰 이동"""
    success, message, game = await quoridor_service.move_pawn(
        game_id, request.row, request.col
    )

    if not success:
        if message == "Game not found":
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"error": "game_not_found", "message": message}
            )
        return ActionResponse(
            success=False,
            message=message,
            error="invalid_move"
        )

    return ActionResponse(
        success=True,
        game_state=game.to_dict(),
        message=message
    )


@router.post(
    "/games/{game_id}/wall",
    response_model=ActionResponse,
    summary="벽 설치",
    description="현재 턴 플레이어가 벽을 설치합니다.",
)
async def place_wall(game_id: str, request: WallRequest):
    """벽 설치"""
    success, message, game = await quoridor_service.place_wall(
        game_id,
        request.row,
        request.col,
        request.orientation
    )

    if not success:
        if message == "Game not found":
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"error": "game_not_found", "message": message}
            )

        error_code = "invalid_wall_position"
        if "No walls remaining" in message:
            error_code = "no_walls_remaining"
        elif "path" in message.lower():
            error_code = "path_blocked"

        return ActionResponse(
            success=False,
            message=message,
            error=error_code
        )

    return ActionResponse(
        success=True,
        game_state=game.to_dict(),
        message=message
    )


@router.post(
    "/games/{game_id}/ai-move",
    response_model=AIActionResponse,
    summary="AI 턴 요청",
    description="AI가 자동으로 턴을 수행합니다.",
)
async def ai_move(game_id: str):
    """AI 턴 수행"""
    success, message, action, game = await quoridor_service.ai_move(game_id)

    if not success:
        if message == "Game not found":
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"error": "game_not_found", "message": message}
            )
        return AIActionResponse(
            success=False,
            message=message,
            error="ai_error"
        )

    return AIActionResponse(
        success=True,
        action=action,
        game_state=game.to_dict(),
        message=message
    )


@router.get(
    "/games/{game_id}/valid-moves",
    response_model=ValidMovesResponse,
    summary="유효한 이동 목록 조회",
    description="현재 턴 플레이어가 수행할 수 있는 모든 유효한 행동을 조회합니다.",
)
async def get_valid_moves(game_id: str):
    """유효한 이동 목록 조회"""
    result = await quoridor_service.get_valid_moves(game_id)
    if not result:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "game_not_found", "message": "Game not found"}
        )

    return ValidMovesResponse(**result)


@router.post(
    "/games/{game_id}/abandon",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="게임 포기",
    description="게임을 포기합니다. 기록은 보존되며 활성 목록에서만 제외됩니다.",
)
async def abandon_game(game_id: str):
    """게임 포기 (기록 보존)"""
    if not await quoridor_service.abandon_game(game_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "game_not_found", "message": "Game not found"}
        )
    return None


@router.delete(
    "/games/{game_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="게임 삭제",
    description="게임을 완전히 삭제합니다. 기록도 숨겨집니다.",
)
async def delete_game(game_id: str):
    """게임 완전 삭제"""
    if not await quoridor_service.delete_game(game_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "game_not_found", "message": "Game not found"}
        )
    return None


# ===== 리플레이 시스템 엔드포인트 =====

@router.get(
    "/games/{game_id}/replay/moves",
    response_model=ReplayMovesResponse,
    summary="리플레이 수 목록 조회",
    description="GameMove 테이블에서 게임의 모든 수를 조회합니다. step_no 순서로 정렬됩니다.",
)
async def get_replay_moves(game_id: str):
    """리플레이용 수 목록 조회"""
    moves = await quoridor_service.get_replay_moves(game_id)
    if moves is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "game_not_found", "message": "Game not found or no moves recorded"}
        )

    return ReplayMovesResponse(
        game_id=game_id,
        moves=moves,
        total_moves=len(moves)
    )


@router.get(
    "/games/{game_id}/replay/state/{step_no}",
    response_model=ReplayStateResponse,
    summary="특정 스텝의 게임 상태 조회",
    description="특정 스텝에서의 게임 상태 스냅샷을 조회합니다. step_no=-1이면 초기 상태를 반환합니다.",
)
async def get_replay_state(game_id: str, step_no: int):
    """리플레이용 특정 스텝 상태 조회"""
    game_state = await quoridor_service.get_state_at_step(game_id, step_no)
    if game_state is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "state_not_found", "message": f"Game state at step {step_no} not found"}
        )

    return ReplayStateResponse(
        game_id=game_id,
        step_no=step_no,
        game_state=game_state,
        is_initial=(step_no < 0)
    )


@router.get(
    "/games/{game_id}/replay/total",
    summary="게임 총 수 개수 조회",
    description="게임의 총 수(move) 개수를 조회합니다.",
)
async def get_total_moves(game_id: str):
    """게임 총 수 개수 조회"""
    total = await quoridor_service.get_total_moves(game_id)
    return {"game_id": game_id, "total_moves": total}
