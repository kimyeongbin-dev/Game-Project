# 🎮 My Favorite Games Collection
> **Claude와 Gemini AI를 활용한 나만의 게임 큐레이션 및 멀티 플랫폼 앱**

본 프로젝트는 AI(Claude 3.5 & Gemini)를 활용하여 사용자가 좋아하는 게임들을 수집, 관리하고 분석하는 멀티 플랫폼 애플리케이션입니다. Flutter를 통한 유연한 UI와 FastAPI의 빠른 성능을 결합하여 안드로이드, iOS, Web, PC 모두를 지원합니다.

---

## 🛠 기술 스택 (Tech Stack)

| 구분 | 기술 |
| :--- | :--- |
| **Frontend** | **Flutter** (Dart) |
| **Backend** | **FastAPI** (Python) |
| **AI Models** | **Anthropic Claude 3.5**, **Google Gemini** |
| **Environment** | **Anaconda** (Conda Virtual Environment) |
| **IDE** | **Visual Studio Code** |

---

## 🚀 주요 특징

- **AI 통합 시스템**: Claude와 Gemini API를 동시에 활용하여 게임 정보를 분석하고 사용자 취향에 맞는 게임을 추천합니다.
- **단일 코드베이스**: Flutter 하나로 Android, iOS, Web, Windows 앱을 모두 아우르는 통합 프론트엔드 환경을 구축했습니다.
- **가상환경 최적화**: Anaconda를 활용하여 종속성 충돌 없는 깨끗한 개발 환경을 유지합니다.

---

## 📦 설치 및 실행 방법 (Installation)

### 1. 가상환경 설정 (Anaconda)
프로젝트 구동을 위한 Python 가상환경을 생성하고 활성화합니다.

```bash
# 가상환경 생성
conda create -n GameProject python=3.10

# 가상환경 활성화
conda activate GameProject

# 백엔드 의존성 설치
pip install fastapi uvicorn
```

### 2. 백엔드 서버 실행 (FastAPI)
```bash
# 서버 실행 (backend 폴더 진입 후)
uvicorn main:app --reload
```

### 3. 프론트엔드 실행 (Flutter)
```bash
# 프로젝트 루트로 이동
cd frontend-mobile_flutter

# 웹 지원 추가 (최초 1회)
flutter create .

# 패키지 설치
flutter pub get

# 앱 실행 (Chrome 기준)
flutter run -d chrome
```

### 📂 프로젝트 구조 (Folder Structure)
```plaintext
.
├── backend/               # FastAPI 기반 서버 코드
│   ├── main.py            # 서버 메인 로직
│   └── requirements.txt   # 의존성 목록
├── frontend/              # Flutter 기반 클라이언트 코드
│   ├── lib/               # 앱 소스 코드
│   ├── web/               # 웹 빌드 설정
│   └── pubspec.yaml       # 플러터 패키지 관리
└── README.md              # 프로젝트 문서
```
