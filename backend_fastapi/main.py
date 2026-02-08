"""
Game Project Backend - FastAPI
Phase 1: 기본 인프라 및 API 설정
"""

import sys
from pathlib import Path
from contextlib import asynccontextmanager

# 프로젝트 루트를 path에 추가 (games 패키지 접근용)
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from routers.quoridor import router as quoridor_router
from routers.users import router as users_router
from routers.ranking import router as ranking_router
from database import init_db, close_db
from scheduler import setup_scheduler, shutdown_scheduler


@asynccontextmanager
async def lifespan(app: FastAPI):
    """애플리케이션 생명주기 관리"""
    # 시작: 데이터베이스 초기화
    print("Initializing database...")
    await init_db()
    print("Database initialized successfully")

    # 스케줄러 시작
    print("Starting scheduler...")
    setup_scheduler()
    print("Scheduler started")

    yield

    # 종료: 스케줄러 정리
    print("Shutting down scheduler...")
    shutdown_scheduler()
    print("Scheduler stopped")

    # 종료: 데이터베이스 연결 정리
    print("Closing database connections...")
    await close_db()
    print("Database connections closed")


app = FastAPI(
    title="Game Project API",
    description="게임 허브 백엔드 API - 유저 관리, 게임 정보, 점수 기록",
    version="0.1.0",
    lifespan=lifespan
)

# CORS 설정 (개발 환경)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 프로덕션에서는 특정 도메인만 허용
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
async def root():
    """API 상태 확인"""
    return {"status": "ok", "message": "Game Project API is running"}


@app.get("/health")
async def health_check():
    """헬스 체크 엔드포인트"""
    return {"status": "healthy"}


# Routers
app.include_router(quoridor_router)
app.include_router(users_router)
app.include_router(ranking_router)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
