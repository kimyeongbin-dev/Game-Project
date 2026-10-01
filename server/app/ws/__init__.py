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

## 워커 간 전달 — Redis Pub/Sub (M3 4단계)

서비스가 상태를 쓴 직후 이벤트를 발행하고(`app/services/events.py`), 워커마다 버스가
구독해서 **자기 프로세스의 소켓에만** 보낸다. 게임·방 소속은 Redis 가 권위이고,
여기 남은 프로세스 내 상태는 연결 맵(user_id → 소켓) 하나다.

| 모듈 | 책임 |
| :-- | :-- |
| `connection_manager` | 이 워커의 연결 맵. 소켓 객체는 본래 프로세스 안에 있다 |
| `bus` | 패턴 구독 1개, 수신자 ∩ 로컬 유저에게 전달, 끊기면 재구독 후 재동기화 |
| `delivery` | 이벤트 → 수신자별 메시지(게임은 좌석별 화면, §6), 활동별 재동기화 |

**maze WS 핸들러(docs/api/games/maze.md §12)는 7단계에서 새로 작성**하고 그때
`main.py` 에 등록한다. 구 핸들러가 필요하면 `git show <커밋>^:server/app/ws/ws_game.py`
로 꺼내 참고만 한다.
"""

from .connection_manager import ConnectionManager, connection_manager

__all__ = [
    'ConnectionManager',
    'connection_manager',
]
