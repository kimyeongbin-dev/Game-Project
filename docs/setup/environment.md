# 개발 환경 구성

> 로컬 개발 환경 설정 및 Docker 가이드

---

## 기술 스택

| 구분 | 기술 | 버전 |
|------|------|------|
| **Backend** | FastAPI | 0.128.0 |
| **Runtime** | Python | 3.11 |
| **Database** | PostgreSQL | 16 |
| **ORM** | SQLAlchemy (async) | 2.0.46 |
| **Frontend** | Flutter | 3.x |
| **Container** | Docker + Docker Compose | - |

---

## 환경 선택

### 옵션 1: Docker 환경 (권장)

의존성 설치 없이 바로 실행 가능합니다.

```bash
# 컨테이너 실행
docker-compose up -d

# 상태 확인
docker-compose ps

# 로그 확인
docker-compose logs -f backend
```

**구성:**
- `quoridor-backend`: FastAPI 서버 (포트 8000)
- `quoridor-db`: PostgreSQL 데이터베이스 (포트 5432)

### 옵션 2: Anaconda + Docker DB

로컬에서 백엔드를 직접 실행하고, DB만 Docker 사용합니다.

```bash
# 1. DB만 Docker로 실행
docker compose up db -d

# 2. Conda 환경 활성화
E:/Conda/Scripts/activate && conda activate GameProject

# 3. 의존성 설치 (최초 1회)
pip install -r backend_fastapi/requirements.txt

# 4. 백엔드 서버 실행
cd backend_fastapi
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

### 옵션 3: DB 없이 실행

메모리 모드로 동작합니다 (데이터 영속성 없음).

```bash
set DB_ENABLED=false
uvicorn main:app --reload
```

---

## 로컬 개발 테스트 (모바일 포함)

로컬 서버 + Docker DB + Flutter로 모바일 기기에서 테스트할 때:

**1. Docker PostgreSQL**
```bash
docker compose up db -d
```

**2. 백엔드 서버**
```bash
cd backend_fastapi
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

**3. 프론트엔드**
```bash
cd frontend_flutter
flutter run -d web-server --web-port=3000 --release
```

**접속:**
- 노트북: `http://localhost:3000`
- 모바일: `http://{노트북IP}:3000` (예: `http://192.168.0.16:3000`)

**동작 방식:**
| 항목 | `flutter run -d web-server` | Docker + static files |
|------|-----------------------------|-----------------------|
| 코드 수정 | Hot Reload (release 제외) | 매번 빌드 필요 |
| 용도 | 로컬 개발/테스트 | 배포/프로덕션 |

---

## 환경 변수

`.env.example`을 `.env`로 복사 후 설정:

```bash
# PostgreSQL 설정
POSTGRES_DB=quoridor_db
POSTGRES_USER=postgres
POSTGRES_PASSWORD=your_password_here

# 백엔드 설정
DB_ENABLED=true
LOG_LEVEL=INFO
```

---

## Flutter 접속 설정

Docker 백엔드에 접속할 때 플랫폼별 URL:

| 플랫폼 | API Base URL |
|--------|--------------|
| Web (Chrome) | `http://localhost:8000` |
| Android 에뮬레이터 | `http://10.0.2.2:8000` |
| iOS 시뮬레이터 | `http://localhost:8000` |
| Windows/macOS/Linux | `http://localhost:8000` |
| 실제 기기 (같은 네트워크) | `http://<PC IP>:8000` |

---

## 유용한 명령어

### Docker
```bash
# 시작/중지
docker-compose up -d
docker-compose down

# 로그
docker-compose logs -f backend

# 컨테이너 내부 접속
docker exec -it quoridor-backend bash

# 테스트 실행
docker exec quoridor-backend pytest

# DB 접속
docker exec -it quoridor-db psql -U postgres -d quoridor_db

# 이미지 재빌드
docker-compose build --no-cache backend
```

### Anaconda
```bash
# 환경 활성화
conda activate GameProject

# 테스트
cd backend_fastapi && pytest

# 서버 실행
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

### Flutter
```bash
cd frontend_flutter

# 의존성 설치
flutter pub get

# 실행
flutter run -d chrome      # 웹
flutter run -d windows     # 윈도우
flutter run -d <device>    # 에뮬레이터/실기기
```

---

## 트러블슈팅

### Docker Desktop 미실행
```
error during connect: ... open //./pipe/dockerDesktopLinuxEngine
```
→ Docker Desktop을 시작하세요.

### 포트 충돌
```bash
# 사용 중인 포트 확인 (Windows)
netstat -ano | findstr :8000
netstat -ano | findstr :5432
```

### DB 연결 실패
- Docker: `docker-compose logs db`로 상태 확인
- 로컬: PostgreSQL 서비스 실행 여부 확인, 또는 `DB_ENABLED=false` 설정

### Hot Reload 미작동
```bash
docker-compose restart backend
```
