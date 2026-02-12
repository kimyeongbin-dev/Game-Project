"""
Quoridor API Router
쿼리도 게임 REST API 엔드포인트
"""

from typing import Optional
from fastapi import APIRouter, HTTPException, status, Query, Request, Header

from middleware.rate_limiter import limiter
from routers.users import get_current_user
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
@limiter.limit("30/minute")
async def get_active_sessions(request: Request, limit: int = Query(default=50, ge=1, le=100)):
    """진행 중인 게임 세션 목록 조회"""
    sessions = await quoridor_service.get_active_sessions(limit=limit)
    return ActiveSessionsResponse(sessions=sessions, count=len(sessions))


@router.post(
    "/games",
    response_model=CreateGameResponse,
    status_code=status.HTTP_201_CREATED,
    summary="새 게임 생성",
    description="새로운 쿼리도 게임을 생성합니다. 모든 게임 모드는 로그인이 필요합니다.",
)
@limiter.limit("10/minute")
async def create_game(
    request: Request,
    body: CreateGameRequest = CreateGameRequest(),
    authorization: Optional[str] = Header(None)
):
    """
    새 게임 생성
    - vs_ai: AI 대전 (일반 대전)
    - ranked: 랭킹전 (온라인 2P 대전) - 랭킹에 반영
    - friend_match: 친구대전 (방 코드 기반)

    모든 게임 모드는 로그인이 필요합니다.
    """
    # 모든 게임 모드에서 인증 필수
    if not authorization:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error": "auth_required", "message": "게임을 시작하려면 로그인이 필요합니다"}
        )
    user = await get_current_user(authorization)

    # 랭킹전 여부는 game_mode로 판단
    is_ranked = (body.game_mode == "ranked")

    game, _, _ = await quoridor_service.create_game(
        player1_name=user.nickname,
        player2_name="AI" if body.game_mode == "vs_ai" else "대기 중...",
        ai_difficulty=body.ai_difficulty,
        game_mode=body.game_mode,
        is_ranked=is_ranked,
        player1_user_id=user.id
    )

    return CreateGameResponse(
        game_id=game.game_id,
        status=game.status.value,
        game_mode=game.game_mode.value,
        current_turn=game.current_turn,
        is_ranked=is_ranked,
        player_user_id=user.id,
        message="Game created successfully"
    )


@router.get(
    "/games/{game_id}",
    response_model=GameStateSchema,
    summary="게임 상태 조회",
    description="현재 게임 상태를 조회합니다. 메모리에 없으면 DB에서 자동 복구합니다.",
)
@limiter.limit("60/minute")
async def get_game(request: Request, game_id: str):
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
@limiter.limit("20/minute")
async def recover_game(request: Request, game_id: str):
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
@limiter.limit("30/minute")
async def get_game_history(request: Request, game_id: str):
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
@limiter.limit("120/minute")
async def move_pawn(request: Request, game_id: str, body: MoveRequest):
    """폰 이동"""
    success, message, game = await quoridor_service.move_pawn(
        game_id, body.row, body.col
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
@limiter.limit("120/minute")
async def place_wall(request: Request, game_id: str, body: WallRequest):
    """벽 설치"""
    success, message, game = await quoridor_service.place_wall(
        game_id,
        body.row,
        body.col,
        body.orientation
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
@limiter.limit("120/minute")
async def ai_move(request: Request, game_id: str):
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
@limiter.limit("120/minute")
async def get_valid_moves(request: Request, game_id: str):
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
@limiter.limit("10/minute")
async def abandon_game(request: Request, game_id: str):
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
@limiter.limit("10/minute")
async def delete_game(request: Request, game_id: str):
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
@limiter.limit("30/minute")
async def get_replay_moves(request: Request, game_id: str):
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
@limiter.limit("60/minute")
async def get_replay_state(request: Request, game_id: str, step_no: int):
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
@limiter.limit("60/minute")
async def get_total_moves(request: Request, game_id: str):
    """게임 총 수 개수 조회"""
    total = await quoridor_service.get_total_moves(game_id)
    return {"game_id": game_id, "total_moves": total}
