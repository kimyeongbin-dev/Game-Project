"""
실시간 멀티플레이 WebSocket 계층.

## 현재 상태 — 연결 관리만 남았다

M3 3단계에서 구 Quoridor 2P 이식분(`ws_game`·`room_manager`·`matchmaking`)과
`quoridor_service` shim 을 삭제했다. 큐·방·게임 상태는 Redis 로 옮겨 아래 서비스가 맡는다:

| 상태 | 담당 |
| :-- | :-- |
| 매치메이킹 큐 | `app/services/matchmaking.py` |
| 친구 대전 방 | `app/services/rooms.py` |
| 진행 중 게임 상태·종료 기록 | `app/services/maze_game.py` |

남은 `connection_manager` 는 소켓 객체를 다루므로 본래 프로세스 안에 있다.
워커 간 메시지 전달은 4단계에서 Redis Pub/Sub 으로 붙인다.

**maze WS 핸들러(docs/api/games/maze.md §12)는 7단계에서 새로 작성**하고 그때
`main.py` 에 등록한다. 구 핸들러가 필요하면 `git show <커밋>^:server/app/ws/ws_game.py`
로 꺼내 참고만 한다.
"""

from .connection_manager import ConnectionManager, connection_manager

__all__ = [
    'ConnectionManager',
    'connection_manager',
]
