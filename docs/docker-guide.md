# Docker 개발 환경 가이드

## 빠른 시작

### 1. Docker 컨테이너 실행

```bash
# 프로젝트 루트에서 실행
docker-compose up -d

# 로그 확인
docker-compose logs -f backend
```

### 2. 서버 상태 확인

```bash
# Health check
curl http://localhost:8000/health

# API 문서
# 브라우저에서: http://localhost:8000/docs
```

### 3. 컨테이너 중지

```bash
docker-compose down

# 볼륨까지 삭제 (DB 데이터 초기화)
docker-compose down -v
```

---

## Flutter에서 Docker 서버 접속

### Web (Chrome)
```dart
const baseUrl = 'http://localhost:8000';
```

### Android 에뮬레이터
```dart
// Android 에뮬레이터는 10.0.2.2가 호스트의 localhost를 가리킴
const baseUrl = 'http://10.0.2.2:8000';
```

### iOS 시뮬레이터
```dart
// iOS 시뮬레이터는 localhost 직접 사용 가능
const baseUrl = 'http://localhost:8000';
```

### 실제 기기 (같은 네트워크)
```dart
// 호스트 PC의 IP 주소 사용
const baseUrl = 'http://192.168.x.x:8000';
```

### 권장: 환경별 자동 설정
```dart
String getBaseUrl() {
  if (kIsWeb) {
    return 'http://localhost:8000';
  } else if (Platform.isAndroid) {
    return 'http://10.0.2.2:8000';
  } else if (Platform.isIOS) {
    return 'http://localhost:8000';
  } else {
    // Windows, macOS, Linux 데스크톱
    return 'http://localhost:8000';
  }
}
```

---

## Hot Reload 설정

로컬 코드 수정 시 Docker 컨테이너에 자동 반영됩니다.

**설정된 Volume Mounts:**
- `./backend_fastapi` -> `/app` (FastAPI 코드)
- `./games` -> `/app/../games` (게임 엔진 코드)

uvicorn의 `--reload` 옵션이 파일 변경을 감지하여 자동으로 서버를 재시작합니다.

---

## 유용한 명령어

```bash
# 컨테이너 내부 접속
docker exec -it quoridor-backend bash

# 테스트 실행
docker exec quoridor-backend pytest

# DB 접속
docker exec -it quoridor-db psql -U postgres -d quoridor_db

# 이미지 재빌드 (requirements.txt 변경 시)
docker-compose build --no-cache backend
docker-compose up -d
```

---

## 환경 변수

`.env` 파일에서 설정:

| 변수 | 기본값 | 설명 |
|------|--------|------|
| POSTGRES_DB | quoridor_db | 데이터베이스 이름 |
| POSTGRES_USER | postgres | DB 사용자 |
| POSTGRES_PASSWORD | 8755 | DB 비밀번호 |
| DB_ENABLED | true | DB 사용 여부 |

---

## 트러블슈팅

### 포트 충돌
```bash
# 사용 중인 포트 확인
netstat -ano | findstr :8000
netstat -ano | findstr :5432
```

### DB 연결 실패
```bash
# DB 컨테이너 상태 확인
docker-compose ps db
docker-compose logs db
```

### 코드 변경이 반영 안 됨
```bash
# 컨테이너 재시작
docker-compose restart backend
```
