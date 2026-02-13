# Database Schema Design

## Overview

Game Project용 SQLite 데이터베이스 스키마 설계서입니다.
Phase 1에서는 유저 정보, 게임 정보, 점수 기록을 관리합니다.

---

## ERD (Entity Relationship Diagram)

```
┌─────────────┐       ┌─────────────┐       ┌─────────────┐
│   users     │       │   games     │       │   scores    │
├─────────────┤       ├─────────────┤       ├─────────────┤
│ id (PK)     │       │ id (PK)     │       │ id (PK)     │
│ username    │       │ name        │       │ user_id(FK) │──┐
│ email       │       │ slug        │       │ game_id(FK) │──┤
│ password    │       │ description │       │ score       │  │
│ nickname    │       │ min_players │       │ result      │  │
│ created_at  │       │ max_players │       │ played_at   │  │
│ updated_at  │       │ is_active   │       │ metadata    │  │
└─────────────┘       │ created_at  │       └─────────────┘  │
      │               └─────────────┘             │          │
      │                     │                     │          │
      └─────────────────────┴─────────────────────┘          │
                            │                                │
                            └────────────────────────────────┘
```

---

## Tables

### 1. users (유저 정보)

| Column     | Type         | Constraints                | Description      |
|------------|--------------|----------------------------|------------------|
| id         | INTEGER      | PRIMARY KEY, AUTOINCREMENT | 유저 고유 ID     |
| username   | VARCHAR(50)  | UNIQUE, NOT NULL           | 로그인용 아이디  |
| email      | VARCHAR(100) | UNIQUE, NOT NULL           | 이메일 주소      |
| password   | VARCHAR(255) | NOT NULL                   | 해시된 비밀번호  |
| nickname   | VARCHAR(50)  | NOT NULL                   | 게임 내 닉네임   |
| created_at | DATETIME     | DEFAULT CURRENT_TIMESTAMP  | 가입일시         |
| updated_at | DATETIME     | DEFAULT CURRENT_TIMESTAMP  | 정보 수정일시    |

```sql
CREATE TABLE users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username VARCHAR(50) UNIQUE NOT NULL,
    email VARCHAR(100) UNIQUE NOT NULL,
    password VARCHAR(255) NOT NULL,
    nickname VARCHAR(50) NOT NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_users_username ON users(username);
CREATE INDEX idx_users_email ON users(email);
```

---

### 2. games (게임 정보)

| Column      | Type         | Constraints                | Description          |
|-------------|--------------|----------------------------|----------------------|
| id          | INTEGER      | PRIMARY KEY, AUTOINCREMENT | 게임 고유 ID         |
| name        | VARCHAR(100) | NOT NULL                   | 게임 표시명          |
| slug        | VARCHAR(50)  | UNIQUE, NOT NULL           | URL/폴더용 식별자    |
| description | TEXT         |                            | 게임 설명            |
| min_players | INTEGER      | DEFAULT 1                  | 최소 플레이어 수     |
| max_players | INTEGER      | DEFAULT 1                  | 최대 플레이어 수     |
| is_active   | BOOLEAN      | DEFAULT TRUE               | 활성화 여부          |
| created_at  | DATETIME     | DEFAULT CURRENT_TIMESTAMP  | 등록일시             |

```sql
CREATE TABLE games (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name VARCHAR(100) NOT NULL,
    slug VARCHAR(50) UNIQUE NOT NULL,
    description TEXT,
    min_players INTEGER DEFAULT 1,
    max_players INTEGER DEFAULT 1,
    is_active BOOLEAN DEFAULT TRUE,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_games_slug ON games(slug);
CREATE INDEX idx_games_is_active ON games(is_active);
```

**초기 데이터 예시:**
```sql
INSERT INTO games (name, slug, description, min_players, max_players) VALUES
    ('쿼리도', 'quoridor', '벽을 세워 상대를 막는 전략 보드게임', 2, 4),
    ('오목', 'gomoku', '5개의 돌을 연속으로 놓으면 승리', 2, 2);
```

---

### 3. scores (게임 기록)

| Column    | Type     | Constraints                | Description              |
|-----------|----------|----------------------------|--------------------------|
| id        | INTEGER  | PRIMARY KEY, AUTOINCREMENT | 기록 고유 ID             |
| user_id   | INTEGER  | FOREIGN KEY, NOT NULL      | 유저 ID (users.id 참조)  |
| game_id   | INTEGER  | FOREIGN KEY, NOT NULL      | 게임 ID (games.id 참조)  |
| score     | INTEGER  | DEFAULT 0                  | 점수 (게임별 의미 다름)  |
| result    | VARCHAR(20) |                         | 결과 (win/lose/draw)     |
| played_at | DATETIME | DEFAULT CURRENT_TIMESTAMP  | 플레이 일시              |
| metadata  | TEXT     |                            | 추가 정보 (JSON)         |

```sql
CREATE TABLE scores (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    game_id INTEGER NOT NULL,
    score INTEGER DEFAULT 0,
    result VARCHAR(20),
    played_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    metadata TEXT,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
    FOREIGN KEY (game_id) REFERENCES games(id) ON DELETE CASCADE
);

CREATE INDEX idx_scores_user_id ON scores(user_id);
CREATE INDEX idx_scores_game_id ON scores(game_id);
CREATE INDEX idx_scores_played_at ON scores(played_at);
```

---

## 전체 스키마 SQL

```sql
-- Game Project Database Schema
-- SQLite 3.x

PRAGMA foreign_keys = ON;

-- Users Table
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username VARCHAR(50) UNIQUE NOT NULL,
    email VARCHAR(100) UNIQUE NOT NULL,
    password VARCHAR(255) NOT NULL,
    nickname VARCHAR(50) NOT NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- Games Table
CREATE TABLE IF NOT EXISTS games (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name VARCHAR(100) NOT NULL,
    slug VARCHAR(50) UNIQUE NOT NULL,
    description TEXT,
    min_players INTEGER DEFAULT 1,
    max_players INTEGER DEFAULT 1,
    is_active BOOLEAN DEFAULT TRUE,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- Scores Table
CREATE TABLE IF NOT EXISTS scores (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    game_id INTEGER NOT NULL,
    score INTEGER DEFAULT 0,
    result VARCHAR(20),
    played_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    metadata TEXT,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
    FOREIGN KEY (game_id) REFERENCES games(id) ON DELETE CASCADE
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_users_username ON users(username);
CREATE INDEX IF NOT EXISTS idx_users_email ON users(email);
CREATE INDEX IF NOT EXISTS idx_games_slug ON games(slug);
CREATE INDEX IF NOT EXISTS idx_games_is_active ON games(is_active);
CREATE INDEX IF NOT EXISTS idx_scores_user_id ON scores(user_id);
CREATE INDEX IF NOT EXISTS idx_scores_game_id ON scores(game_id);
CREATE INDEX IF NOT EXISTS idx_scores_played_at ON scores(played_at);
```

---

## 확장 고려사항 (Phase 2+)

- **sessions**: 멀티플레이어 게임 세션 관리
- **friends**: 친구 관계 테이블
- **achievements**: 업적 시스템
- **leaderboards**: 랭킹 캐시 테이블
