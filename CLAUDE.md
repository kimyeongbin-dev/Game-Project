# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

A multi-platform game application featuring Quoridor (board game) with AI opponent. Built with Flutter frontend and FastAPI backend, supporting PostgreSQL with fallback to memory-only mode.

## Development Commands

### Backend (FastAPI)
```bash
# Activate conda environment first (required for all commands)
E:/Conda/Scripts/activate && conda activate GameProject

# Install dependencies
pip install -r backend_fastapi/requirements.txt

# Run server (from backend_fastapi directory)
cd backend_fastapi && uvicorn main:app --reload

# Run tests
pytest
```

### Frontend (Flutter)
```bash
cd frontend_flutter
flutter pub get
flutter run -d chrome    # Web
flutter run -d windows   # Windows desktop
```

### Database
- PostgreSQL required for persistence, but server gracefully degrades to memory-only mode
- Set `DB_ENABLED=false` env var to disable DB
- Default connection: `postgresql+asyncpg://postgres:postgres@localhost:5432/quoridor_db`

## Architecture

### Three-Layer Game Structure
1. **Game Engine** (`games/`): Pure Python game logic, no framework dependencies
   - `games/game_Quoridor/core/`: Board, Player, Wall, GameState, MoveValidator, Pathfinder
   - `games/game_Quoridor/ai/`: SimpleAI with difficulty levels

2. **Backend API** (`backend_fastapi/`): FastAPI REST layer
   - `services/quoridor_service.py`: Business logic, manages game instances in memory + DB
   - `routers/quoridor.py`: REST endpoints
   - `database/`: PostgreSQL via SQLAlchemy async

3. **Frontend** (`frontend_flutter/`): Flutter multi-platform UI
   - `lib/services/api_service.dart`: Backend communication
   - `lib/screens/quoridor_screen.dart`: Game screen
   - `lib/widgets/`: Board rendering components

### Key Design Patterns
- **Game State Serialization**: `GameState.to_dict()` / `GameState.from_dict()` for DB persistence
- **Graceful Degradation**: Server runs without DB (memory-only), `is_db_available()` checks before DB ops
- **Service Singleton**: `quoridor_service` instance manages all game state

## Quoridor Game Coordinates
- Board: 9x9 grid (0-8)
- Walls: 2-cell length, placed at intersections (0-7 range)
- Player 1 starts at (8,4), goal row 0
- Player 2/AI starts at (0,4), goal row 8

## API Base Path
`/api/v1/quoridor` - See `docs/quoridor/api_spec.md` for full specification

## Logging Guidelines

### Log Levels
- **DEBUG**: 모든 로그 (SQL 쿼리 포함) - 디버깅용
- **INFO**: 핵심 비즈니스 로직만 - 개발용 (기본값)
- **WARNING**: 경고/에러만 - 배포용

### INFO 레벨 로그 규칙
새로운 기능을 구현할 때 반드시 INFO 레벨 로그를 추가해야 합니다.

**필수 로깅 대상:**
- 사용자 인증: 회원가입, 로그인, 로그아웃
- 게임 이벤트: 게임 생성, 시작, 종료, 포기
- 매칭 시스템: 대기열 참가/나가기, 매칭 완료
- 게임 액션: 말 이동, 벽 설치, 항복
- 방 관리: 방 생성, 참가, 나가기, 준비 완료

**로그 형식:**
```python
import logging
logger = logging.getLogger(__name__)

# 형식: [기능명] 주요정보 (부가정보)
logger.info(f"[회원가입] {user.nickname}")
logger.info(f"[게임 생성] {user.nickname} (모드: {game_mode}, 게임: {game_id[:8]})")
logger.info(f"[말 이동] {user.nickname} -> ({row}, {col}) (게임: {game_id[:8]})")
logger.info(f"[대기열 참가] {user.nickname} (위치: {position})")
```

**주의사항:**
- game_id는 처음 8자리만 표시 (`game_id[:8]`)
- SQLAlchemy 및 연결 로그는 INFO에서 표시하지 않음
- WebSocket 연결/해제는 이미 로깅됨
