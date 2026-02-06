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
