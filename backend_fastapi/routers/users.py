"""
User Router
유저 등록/로그인 API
"""

import logging
from typing import Optional
from fastapi import APIRouter, Header, HTTPException, status, Request
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)

from database import get_db_session, is_db_available
from database.repository import UserRepository, RankingRepository, GameSessionRepository
from database.memory_store import memory_store
from middleware.rate_limiter import limiter
from schemas.users import (
    RegisterRequest, RegisterResponse,
    LoginRequest, LoginResponse,
    UserInfoResponse, HeartbeatResponse, LogoutResponse,
    ResetTimeInfo, GameHistoryExportResponse, GameHistoryExportEntry
)
from scheduler import get_next_reset_time, get_time_until_reset


# 서버 시작 시 테스트 유저 초기화
memory_store.initialize_test_users()

router = APIRouter(prefix="/api/v1/users", tags=["Users"])


def get_reset_time_info() -> ResetTimeInfo:
    """리셋 시간 정보 생성"""
    next_reset = get_next_reset_time()
    remaining = get_time_until_reset()

    # 남은 시간을 HH:MM:SS 형식으로
    total_seconds = int(remaining.total_seconds())
    hours, remainder = divmod(total_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)

    return ResetTimeInfo(
        next_reset_at=next_reset.isoformat(),
        time_remaining=f"{hours:02d}:{minutes:02d}:{seconds:02d}",
        reset_hour_kst=9
    )


async def get_current_user(authorization: Optional[str] = Header(None)):
    """
    현재 유저 조회 (토큰 인증)
    Authorization: Bearer <token>
    """
    if not authorization:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authorization header required"
        )

    # Bearer 토큰 파싱
    parts = authorization.split()
    if len(parts) != 2 or parts[0].lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authorization format. Use: Bearer <token>"
        )

    token = parts[1]

    # DB가 없으면 인메모리 스토어 사용
    if not is_db_available():
        user = memory_store.get_by_token(token)
        if not user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or expired token"
            )
        return user

    async for session in get_db_session():
        if session is None:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Database session not available"
            )

        repo = UserRepository(session)
        user = await repo.get_by_token(token)

        if not user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or expired token"
            )

        return user


@router.post("/register", response_model=RegisterResponse, status_code=status.HTTP_201_CREATED)
@limiter.limit("5/minute")
async def register_user(request: Request, body: RegisterRequest):
    """
    새 유저 등록
    - 닉네임 중복 체크
    - 세션 토큰 발급
    """
    # DB가 없으면 인메모리 스토어 사용
    if not is_db_available():
        user, error = memory_store.create_user(body.nickname, body.password)
        if not user:
            return RegisterResponse(
                success=False,
                message=error,
                error="registration_failed"
            )
        logger.info(f"[회원가입] {user.nickname} (메모리 모드)")
        return RegisterResponse(
            success=True,
            user_id=user.id,
            nickname=user.nickname,
            session_token=user.session_token,
            reset_info=get_reset_time_info(),
            message="등록 완료 (메모리 모드). 매일 오전 9시(KST)에 랭킹이 초기화됩니다."
        )

    async for session in get_db_session():
        if session is None:
            return RegisterResponse(
                success=False,
                message="Database session not available",
                error="db_unavailable"
            )

        repo = UserRepository(session)
        user, error = await repo.create(body.nickname, body.password)

        if not user:
            return RegisterResponse(
                success=False,
                message=error,
                error="registration_failed"
            )

        logger.info(f"[회원가입] {user.nickname}")
        return RegisterResponse(
            success=True,
            user_id=user.id,
            nickname=user.nickname,
            session_token=user.session_token,
            reset_info=get_reset_time_info(),
            message="등록 완료. 매일 오전 9시(KST)에 랭킹이 초기화됩니다."
        )


@router.post("/login", response_model=LoginResponse)
@limiter.limit("10/minute")
async def login_user(request: Request, body: LoginRequest):
    """
    기존 유저 로그인
    - 닉네임으로 조회
    - 새 세션 토큰 발급
    """
    # DB가 없으면 인메모리 스토어 사용
    if not is_db_available():
        user, error = memory_store.login(body.nickname, body.password)
        if not user:
            return LoginResponse(
                success=False,
                message=error,
                error="login_failed"
            )
        logger.info(f"[로그인] {user.nickname} (메모리 모드)")
        return LoginResponse(
            success=True,
            user_id=user.id,
            nickname=user.nickname,
            session_token=user.session_token,
            score=user.score,
            wins=user.wins,
            losses=user.losses,
            best_turn_count=user.best_turn_count,
            reset_info=get_reset_time_info(),
            message="로그인 완료 (메모리 모드). 매일 오전 9시(KST)에 랭킹이 초기화됩니다."
        )

    async for session in get_db_session():
        if session is None:
            return LoginResponse(
                success=False,
                message="Database session not available",
                error="db_unavailable"
            )

        repo = UserRepository(session)
        user, error = await repo.login(body.nickname, body.password)

        if not user:
            return LoginResponse(
                success=False,
                message=error,
                error="login_failed"
            )

        logger.info(f"[로그인] {user.nickname}")
        return LoginResponse(
            success=True,
            user_id=user.id,
            nickname=user.nickname,
            session_token=user.session_token,
            score=user.score,
            wins=user.wins,
            losses=user.losses,
            best_turn_count=user.best_turn_count,
            reset_info=get_reset_time_info(),
            message="로그인 완료. 매일 오전 9시(KST)에 랭킹이 초기화됩니다."
        )


@router.get("/me", response_model=UserInfoResponse)
@limiter.limit("30/minute")
async def get_my_info(request: Request, authorization: Optional[str] = Header(None)):
    """
    내 정보 조회
    """
    user = await get_current_user(authorization)

    # DB가 없으면 인메모리 스토어 사용
    if not is_db_available():
        rank = memory_store.get_user_rank(user.id)
        yesterday_champion = memory_store.get_yesterday_champion()
        is_champion = yesterday_champion and yesterday_champion.nickname == user.nickname

        return UserInfoResponse(
            user_id=user.id,
            nickname=user.nickname,
            score=user.score,
            wins=user.wins,
            losses=user.losses,
            best_turn_count=user.best_turn_count,
            rank=rank,
            is_champion=is_champion,
            reset_info=get_reset_time_info()
        )

    async for session in get_db_session():
        if session is None:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Database session not available"
            )

        ranking_repo = RankingRepository(session)
        rank = await ranking_repo.get_user_rank(user.id)

        # 전날 챔피언 체크
        yesterday_champion = await ranking_repo.get_yesterday_champion()
        is_champion = bool(yesterday_champion and yesterday_champion.nickname == user.nickname)

        return UserInfoResponse(
            user_id=user.id,
            nickname=user.nickname,
            score=user.score,
            wins=user.wins,
            losses=user.losses,
            best_turn_count=user.best_turn_count,
            rank=rank,
            is_champion=is_champion,
            reset_info=get_reset_time_info()
        )


@router.post("/heartbeat", response_model=HeartbeatResponse)
@limiter.limit("120/minute")
async def heartbeat(request: Request, authorization: Optional[str] = Header(None)):
    """
    접속 상태 유지 (heartbeat)
    - 30초마다 호출 권장
    """
    user = await get_current_user(authorization)

    # DB가 없으면 인메모리 스토어 사용
    if not is_db_available():
        success = memory_store.update_heartbeat(user.id)
        return HeartbeatResponse(success=success, message="OK" if success else "Failed")

    async for session in get_db_session():
        if session is None:
            return HeartbeatResponse(success=False, message="Database not available")

        repo = UserRepository(session)
        success = await repo.update_heartbeat(user.id)

        return HeartbeatResponse(
            success=success,
            message="OK" if success else "Failed"
        )


@router.post("/logout", response_model=LogoutResponse)
@limiter.limit("10/minute")
async def logout(request: Request, authorization: Optional[str] = Header(None)):
    """
    로그아웃
    - 온라인 상태 해제
    - 현재 게임 연결 해제
    """
    user = await get_current_user(authorization)

    # DB가 없으면 인메모리 스토어 사용
    if not is_db_available():
        success = memory_store.logout(user.id)
        return LogoutResponse(success=success, message="로그아웃 완료" if success else "로그아웃 실패")

    async for session in get_db_session():
        if session is None:
            return LogoutResponse(success=False, message="Database not available")

        repo = UserRepository(session)
        success = await repo.logout(user.id)

        return LogoutResponse(
            success=success,
            message="로그아웃 완료" if success else "로그아웃 실패"
        )


@router.get("/check-nickname/{nickname}")
@limiter.limit("20/minute")
async def check_nickname(request: Request, nickname: str):
    """
    닉네임 사용 가능 여부 확인
    """
    if not is_db_available():
        return {"available": False, "message": "Database not available"}

    async for session in get_db_session():
        if session is None:
            return {"available": False, "message": "Database not available"}

        repo = UserRepository(session)

        # 유효성 검사
        is_valid, error = repo.validate_nickname(nickname)
        if not is_valid:
            return {"available": False, "message": error}

        # 중복 검사
        existing = await repo.get_by_nickname(nickname)
        if existing:
            return {"available": False, "message": "이미 사용 중인 닉네임입니다"}

        return {"available": True, "message": "사용 가능한 닉네임입니다"}


@router.get("/my-games", response_model=GameHistoryExportResponse)
@limiter.limit("10/minute")
async def export_my_game_history(request: Request, authorization: Optional[str] = Header(None)):
    """
    내 게임 내역 내보내기 (로컬 저장용)
    - 모든 게임 기록을 JSON 형태로 반환
    - 클라이언트에서 파일로 저장 가능
    """
    user = await get_current_user(authorization)
    from datetime import datetime, timezone, timedelta

    async for session in get_db_session():
        if session is None:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Database session not available"
            )

        game_repo = GameSessionRepository(session)
        games = await game_repo.get_user_games(user.id)

        game_entries = []
        total_wins = 0
        total_losses = 0
        total_score = 0.0

        for game in games:
            # 결과 판정
            if game.winner == 1 and game.player1_user_id == user.id:
                result = "win"
                total_wins += 1
            elif game.winner == 2 and game.player2_user_id == user.id:
                result = "win"
                total_wins += 1
            elif game.winner is not None:
                result = "lose"
                total_losses += 1
            else:
                result = "abandoned"

            # 상대방 이름
            if game.player1_user_id == user.id:
                opponent = game.player2_name
            else:
                opponent = game.player1_name

            game_entries.append(GameHistoryExportEntry(
                game_id=game.game_id,
                game_mode=game.game_mode.value,
                opponent_name=opponent,
                result=result,
                turn_count=game.turn_count,
                score_change=None,  # 추후 구현 가능
                created_at=game.created_at.isoformat() + "Z",
                finished_at=game.updated_at.isoformat() + "Z" if game.winner else None
            ))

        KST = timezone(timedelta(hours=9))
        export_time = datetime.now(KST).isoformat()

        return GameHistoryExportResponse(
            nickname=user.nickname,
            export_time=export_time,
            total_games=len(game_entries),
            games=game_entries,
            summary={
                "total_wins": total_wins,
                "total_losses": total_losses,
                "win_rate": round(total_wins / len(game_entries) * 100, 1) if game_entries else 0,
                "current_score": user.score,
                "best_turn_count": user.best_turn_count
            }
        )
