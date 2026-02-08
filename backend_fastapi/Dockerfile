# FastAPI Backend Dockerfile
# Python 3.11 기반 이미지

FROM python:3.11-slim

# 작업 디렉토리 설정
WORKDIR /workspace

# 시스템 의존성 설치 (PostgreSQL 클라이언트 포함)
RUN apt-get update && apt-get install -y \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# pip 업그레이드
RUN pip install --no-cache-dir --upgrade pip

# 의존성 파일 복사 및 설치 (빌드 컨텍스트: 프로젝트 루트)
COPY backend_fastapi/requirements.txt ./backend_fastapi/
RUN pip install --no-cache-dir -r backend_fastapi/requirements.txt

# 애플리케이션 코드 복사 (개발 시 volume mount로 덮어씀)
COPY backend_fastapi/ ./backend_fastapi/
COPY games/ ./games/

# games 패키지 접근을 위한 PYTHONPATH 설정
ENV PYTHONPATH=/workspace

# 작업 디렉토리를 backend_fastapi로 변경
WORKDIR /workspace/backend_fastapi

# uvicorn 포트 노출
EXPOSE 8000

# 개발 모드로 서버 실행 (--reload 옵션으로 Hot Reload 지원)
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]
