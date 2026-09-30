# core — 공통 코어 모듈

플랫폼 전역에서 재사용되는 인프라 계층. 개별 게임 모듈은 core 에 의존하지만
core 는 어떤 게임 모듈도 참조하지 않는다 (단방향 의존).

| 디렉토리 | 책임 | 관련 명세 |
| :-- | :-- | :-- |
| `auth/` | 비로그인 UUID 발급·관리, 카카오 소셜 로그인, 익명→소셜 계정 병합 | §1.1, §3.3 원칙 2 |
| `storage/` | Drift(SQLite) 로컬 DB, 하드웨어 금고(Secure Storage) 매니저 | §2.1, §3.2 |
| `network/` | Dio REST 클라이언트, WebSocket 매니저 | §3.1 |
| `security/` | AES 암호화, HMAC-SHA256 무결성 검증, Monotonic Clock 시간 조작 방지 | §3.2, §3.3 원칙 1 |
