# core/storage

- Drift(SQLite) 스키마 및 DAO: 낱말 사전, 솔로 세이브 데이터, 해금 상태
- `assets/db/initial_words.sqlite` 번들 사전을 첫 실행 시 로컬 DB로 전개
- 온라인 연결 시 신규 단어만 버전 비교(Delta Sync) 방식으로 패치 (§4.2)
- Flutter Secure Storage 래퍼: Android Keystore(TEE) / iOS Keychain(Secure Enclave)
