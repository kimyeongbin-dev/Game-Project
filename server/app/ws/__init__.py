"""
실시간 멀티플레이 WebSocket 핸들러 (골격).

PLATFORM_ARCHITECTURE.md §5 기준 구성 예정:
- matchmaking.py    : 1:1 / 1:1:1 매치메이킹 큐 (Redis)
- maze_session.py   : 1인칭 미로 서버 측 시야(Raycasting) 필터링
- gomoku_session.py : 오목 실시간 착수 및 서버 측 렌주룰 검증

TODO: API 설계서 확정 후 구현.
"""
