# gomoku_renju — 오목 (렌주룰) (§4.6)

- 15x15 정통 오목, 국제 표준 렌주룰
- 흑돌 금수: 3-3, 4-4, 장목(6목 이상). '가짜 3(거짓 금수)' 판별 재귀 로직 필요
- 솔로: 로컬 Isolate 에서 금수 판정 + AI (Minimax + Alpha-Beta Pruning)
- 온라인: 착수 유효성을 서버가 직접 검증 → `server/app/ws/gomoku_session.py`
