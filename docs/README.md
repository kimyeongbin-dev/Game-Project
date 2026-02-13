# 문서 인덱스

> 프로젝트 문서 목록 및 용도

---

## 설정 (Setup)

| 문서 | 용도 | 대상 |
|------|------|------|
| [environment.md](setup/environment.md) | 개발 환경 설정, Docker, 로컬 테스트 | 신규 개발자, 환경 구축 시 |

---

## 개발 가이드 (Development)

| 문서 | 용도 | 대상 |
|------|------|------|
| [testing.md](development/testing.md) | 테스트 작성 및 실행 가이드 | 테스트 코드 작성 시 |
| [logging.md](development/logging.md) | 로깅 규칙 및 형식 | 새 기능 구현 시 |

---

## API 명세 (API)

| 문서 | 용도 | 대상 |
|------|------|------|
| [rest_api.md](api/rest_api.md) | REST API 엔드포인트 명세 | API 연동 시 |
| [websocket.md](api/websocket.md) | WebSocket 프로토콜 명세 | 실시간 통신 구현 시 |

---

## 아키텍처 (Architecture)

| 문서 | 용도 | 대상 |
|------|------|------|
| [overview.md](architecture/overview.md) | 전체 시스템 구조, 보안 분석 | 프로젝트 이해, 아키텍처 검토 |
| [database.md](architecture/database.md) | DB 스키마 설계 | DB 수정 시 |

---

## 게임별 문서 (Quoridor)

| 문서 | 용도 | 대상 |
|------|------|------|
| [game_rules.md](quoridor/game_rules.md) | 쿼리도 게임 규칙 | 게임 로직 이해 |
| [game_state.md](quoridor/game_state.md) | 게임 상태 스키마 | 상태 직렬화/역직렬화 |
| [frontend.md](quoridor/frontend.md) | 프론트엔드 UI 설계 | UI 수정 시 |

---

## 루트 문서

| 문서 | 용도 |
|------|------|
| [CLAUDE.md](../CLAUDE.md) | Claude Code 전용 지침 (자동 로드) |
| [README.md](../README.md) | 프로젝트 소개 |

---

## 폴더 구조

```
docs/
├── README.md              # 이 파일 (인덱스)
├── setup/
│   └── environment.md     # 환경 설정
├── development/
│   ├── testing.md         # 테스트 가이드
│   └── logging.md         # 로깅 가이드
├── api/
│   ├── rest_api.md        # REST API 명세
│   └── websocket.md       # WebSocket 프로토콜
├── architecture/
│   ├── overview.md        # 시스템 개요
│   └── database.md        # DB 설계
└── quoridor/
    ├── game_rules.md      # 게임 규칙
    ├── game_state.md      # 상태 스키마
    └── frontend.md        # UI 설계
```
