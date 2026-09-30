"""
실시간 멀티플레이 WebSocket 계층.

## 현재 상태 — 재작업 기반 (그대로 운영 불가)

구 Quoridor 2P 실시간 대전 구현을 구조 이전만 하여 옮겨온 상태다.
`main.py` 에 라우터로 등록되어 있지 않으며, §4.1 명세 확정 후 재설계한다.

### 모듈별 판정

| 모듈 | 성격 | 재설계 시 |
| :-- | :-- | :-- |
| `connection_manager` | 게임 무관 인프라 (연결 생명주기) | 구조 유지. 워커 간 브로드캐스트에 Redis Pub/Sub 추가 필요 |
| `room_manager`       | 게임 무관 인프라 (방 상태·코드) | 구조 유지. 상태를 Redis 로 이동 필요 |
| `matchmaking`        | 점수 범위 확장 매칭 로직 | 로직 재사용. 상태 Redis 이동 + 1:1:1(3인) 확장 필요 |
| `ws_game`            | Quoridor 프로토콜 핸들러 | **재설계 대상.** §4.1 의 1인칭 미로 / Fog of War /
                                              서버 측 Raycasting 시야 필터링으로 대체 |

### 반드시 해결해야 하는 구조적 제약

모든 상태가 **프로세스 내 모듈 전역 dict** 다 (`_connections`, `_queue`, `_rooms`).
PLATFORM_ARCHITECTURE.md §2.2 는 Redis 8 이 매치메이킹 큐·실시간 방 상태·턴 타이머·
Pub/Sub 을 전담하도록 규정한다. 현재 구현은 이를 만족하지 못하므로:

- uvicorn 워커를 2개 이상으로 늘리면 워커마다 별개의 큐·방이 생겨 매칭이 깨진다
  (그래서 `server/Dockerfile` prod 가 `--workers 1` 로 고정되어 있다)
- §2.2 의 컨테이너 기반 오토스케일링이 불가능하다

또한 `_try_match` 가 `len(self._queue) < 2` 로 1:1 만 가정한다 — §4.1 의 1:1:1 미지원.
"""

from .connection_manager import ConnectionManager, connection_manager
from .matchmaking import MatchmakingQueue, matchmaking_queue
from .room_manager import RoomManager, room_manager

__all__ = [
    'ConnectionManager',
    'connection_manager',
    'MatchmakingQueue',
    'matchmaking_queue',
    'RoomManager',
    'room_manager',
]
