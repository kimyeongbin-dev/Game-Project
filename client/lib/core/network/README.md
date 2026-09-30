# core/network

- Dio 기반 REST 클라이언트 (인터셉터: JWT 주입, 재시도, 오프라인 감지)
- WebSocket 매니저: 매치메이킹 큐, 턴 동기화, 재접속/하트비트
- 오프라인 솔로 플레이 시에는 이 계층을 전혀 타지 않아야 한다 (Offline-First)
