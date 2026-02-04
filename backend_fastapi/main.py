"""
Game Project Backend - FastAPI
Phase 1: 기본 인프라 및 API 설정
"""

import sys
from pathlib import Path

# 프로젝트 루트를 path에 추가 (games 패키지 접근용)
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from routers.quoridor import router as quoridor_router

app = FastAPI(
    title="Game Project API",
    description="게임 허브 백엔드 API - 유저 관리, 게임 정보, 점수 기록",
    version="0.1.0",
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

# TODO: Phase 1 구현 예정
# - /api/v1/users: 유저 CRUD
# - /api/v1/games: 게임 정보 조회
# - /api/v1/scores: 점수 기록 및 조회


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
