"""
User Router
유저 등록/로그인 API
"""

from typing import Optional
from fastapi import APIRouter, Header, HTTPException, status

from database import get_db_session, is_db_available
from database.repository import UserRepository, RankingRepository
from schemas.users import (
    RegisterRequest, RegisterResponse,
    LoginRequest, LoginResponse,
    UserInfoResponse, HeartbeatResponse, LogoutResponse
)

router = APIRouter(prefix="/api/v1/users", tags=["Users"])


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

    if not is_db_available():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database not available"
        )

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
async def register_user(request: RegisterRequest):
    """
    새 유저 등록
    - 닉네임 중복 체크
    - 세션 토큰 발급
    """
    if not is_db_available():
        return RegisterResponse(
            success=False,
            message="Database not available",
            error="db_unavailable"
        )

    async for session in get_db_session():
        if session is None:
            return RegisterResponse(
                success=False,
                message="Database session not available",
                error="db_unavailable"
            )

        repo = UserRepository(session)
        user, error = await repo.create(request.nickname, request.password)

        if not user:
            return RegisterResponse(
                success=False,
                message=error,
                error="registration_failed"
            )

        return RegisterResponse(
            success=True,
            user_id=user.id,
            nickname=user.nickname,
            session_token=user.session_token,
            message="등록 완료"
        )


@router.post("/login", response_model=LoginResponse)
async def login_user(request: LoginRequest):
    """
    기존 유저 로그인
    - 닉네임으로 조회
    - 새 세션 토큰 발급
    """
    if not is_db_available():
        return LoginResponse(
            success=False,
            message="Database not available",
            error="db_unavailable"
        )

    async for session in get_db_session():
        if session is None:
            return LoginResponse(
                success=False,
                message="Database session not available",
                error="db_unavailable"
            )

        repo = UserRepository(session)
        user, error = await repo.login(request.nickname, request.password)

        if not user:
            return LoginResponse(
                success=False,
                message=error,
                error="login_failed"
            )

        return LoginResponse(
            success=True,
            user_id=user.id,
            nickname=user.nickname,
            session_token=user.session_token,
            score=user.score,
            wins=user.wins,
            losses=user.losses,
            best_turn_count=user.best_turn_count,
            message="로그인 완료"
        )


@router.get("/me", response_model=UserInfoResponse)
async def get_my_info(authorization: Optional[str] = Header(None)):
    """
    내 정보 조회
    """
    user = await get_current_user(authorization)

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
        is_champion = yesterday_champion and yesterday_champion.nickname == user.nickname

        return UserInfoResponse(
            user_id=user.id,
            nickname=user.nickname,
            score=user.score,
            wins=user.wins,
            losses=user.losses,
            best_turn_count=user.best_turn_count,
            rank=rank,
            is_champion=is_champion
        )


@router.post("/heartbeat", response_model=HeartbeatResponse)
async def heartbeat(authorization: Optional[str] = Header(None)):
    """
    접속 상태 유지 (heartbeat)
    - 30초마다 호출 권장
    """
    user = await get_current_user(authorization)

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
async def logout(authorization: Optional[str] = Header(None)):
    """
    로그아웃
    - 온라인 상태 해제
    - 현재 게임 연결 해제
    """
    user = await get_current_user(authorization)

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
async def check_nickname(nickname: str):
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
