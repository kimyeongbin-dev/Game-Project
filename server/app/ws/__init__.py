"""
실시간 멀티플레이 WebSocket 계층.

## 구성

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
| `delivery` | 이벤트 → 수신자별 §12 메시지(게임은 좌석별 화면, §6), 활동별 재동기화 |
| `maze_handler` | `/api/v1/ws/maze` — 인증·§12 10종 디스패치·재접속·끊김 (M3 7단계) |
| `protocol` · `wire` | 봉투·고정 에러 문구 / §12 페이로드 빌더 |
| `runtime` | lifespan 배선 — 버스·스위퍼·큐 티커·서버 유예·끊김 재시도 |
| `rate_limit` | 소켓별 메시지 버킷·유저별 접속 카운터 |
"""

from .connection_manager import ConnectionManager, connection_manager

__all__ = [
    'ConnectionManager',
    'connection_manager',
]
