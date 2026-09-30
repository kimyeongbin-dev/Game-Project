# core/security

§3.2 / §3.3 원칙 1 대응 — 오프라인 솔로 데이터의 "합리적 보안".

- 앱 최초 실행 시 256비트 AES 키 + HMAC 키를 기기 내부에서 난수 생성
- 생성한 키는 하드웨어 금고(Keystore/Keychain)에만 보관, 소스코드 하드코딩 금지
- 세이브 데이터: AES 암호화 + HMAC-SHA256 무결성 해시 검증
- 부팅 후 경과 시간(Monotonic Clock) 기반 시간 조작 방지
