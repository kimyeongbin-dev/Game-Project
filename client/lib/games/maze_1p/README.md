# maze_1p — 1인칭 미로 대결 (§4.1)

- 1:1 / 1:1:1 대결, 1인칭 시점 미로 탐색 + 벽 설치
- 시야 제한(Fog of War): 시야각 내의 벽과 상대 말만 렌더링
- 렌더링: 2.5D Raycasting 또는 Flutter GPU 커스텀 셰이더, 120fps 목표
- 벽 설치 시 모든 플레이어의 목표 도달 경로 존재 여부를 A*/BFS 로 즉시 검증
- 온라인 대결의 시야 필터링은 서버가 수행 (맵핵 방지) → `server/app/ws/maze_session.py`
- 서버 권위 판정 엔진: `server/app/games/maze/`
