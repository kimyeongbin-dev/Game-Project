# 로드맵

> 이 문서는 **실행 순서**를 다룬다. 무엇을 만들 것인가(설계)는
> [`PLATFORM_ARCHITECTURE.md`](../PLATFORM_ARCHITECTURE.md)가 정본이다.
>
> `CLAUDE.md`에 넣지 않는다 — 그 파일은 매 세션 자동 로드되므로 항상 필요한
> 것만 둔다. 이 문서는 작업 계획이 필요할 때만 읽는다.

---

## 두 개의 축을 구분한다

이름이 겹치기 쉬우므로 축마다 다른 표기를 쓴다.

| 축 | 표기 | 정의 위치 | 의미 |
| :--- | :--- | :--- | :--- |
| **출시** | `Phase 1/2/3` | `PLATFORM_ARCHITECTURE.md` §1.2 | Android → iOS 통합 → 웹 확장 |
| **인프라** | `M1`~`M4` | 이 문서 | 개발·배포 기반 정비 |

두 축은 독립이다. 현재 위치는 **출시 `Phase 1`(Android) 진행 중 + 인프라
`M2` 완료 + `M3` 5단계(시야 엔진) 완료**다.

> ⚠️ **git log 읽을 때 주의:** 커밋 `f831c0b`·`e189199`의 제목은 각각
> "Phase 1"·"Phase 2"로 적혀 있다. 이 표기가 굳기 전에 작성된 것이며,
> 실제로는 **인프라 `M1`·`M2`**를 뜻한다. 출시 `Phase`와 무관하다.

---

## 인프라 마일스톤

### M1 — 버전 전수 고정 ✅ 완료

커밋 `f831c0b`

"자동으로 변경되거나 업그레이드되는 일이 절대 없도록" 모든 버전을 고정했다.
서버 직접 의존성 `==`, 전이 의존성 `uv.lock`(URL + SHA256), 컨테이너 이미지
다이제스트, Flutter 패키지 정확 버전, Android SDK 명시, GitHub Actions 커밋 SHA.

가드: [`scripts/check-version-pinning.sh`](../scripts/check-version-pinning.sh) — CI `version-guard` 잡.
갱신: [`scripts/update-image-digests.sh`](../scripts/update-image-digests.sh).

상세는 [`CLAUDE.md`](../CLAUDE.md)의 "버전 고정" 절.

### M2 — Redis 도입 + 레이트 리미터 배선 ✅ 완료

커밋 `e189199`

- `app/core/config.py` — 환경변수 단일 진입점 (pydantic-settings)
- `app/db/redis.py` — 연결 계층. PostgreSQL과 동일한 graceful degradation
- Redis 논리 DB 분리: **0 = 앱 상태, 1 = 테스트, 2 = 레이트 리미터**
- 리미터를 Redis 저장소로 전환하고 `main.py`에 배선. 커스텀 429 + `Retry-After`
- `/health`가 `dependencies.database` / `dependencies.redis` / `rate_limit` 보고
- 테스트 10건으로 배선 고정 (`tests/api/test_rate_limit.py`)

### M3 — WebSocket 상태 Redis 이전 + 1:1:1 확장

**선행 조건:** `docs/api/games/maze.md` 확정 — **완료**(2026-10-01, 계획서:
[`plans/2026-10-01-이동규칙확정.md`](plans/2026-10-01-이동규칙확정.md)). 이동 규칙
본문까지 닫혔으므로 착수 가능하다.

착수 시점에는 `app/ws/`의 상태가 전부 프로세스 내 모듈 전역 dict였다
(`connection_manager._connections`, `matchmaking._queue`, `room_manager._rooms`).
큐·방·게임 상태는 3단계에서 Redis 로 옮겼고, 연결 맵(`connection_manager`)만 남았다.
`PLATFORM_ARCHITECTURE.md` §2.2는 Redis 8이 매치메이킹 큐·실시간 방 상태·
게임 시계와 접속 유예 데드라인·Pub/Sub을 전담하도록 규정한다.

작업:

1. 매치메이킹 큐·방 상태 **+ 진행 중 게임 상태**를 Redis로 이전 — 게임 상태는
   **Redis 권위 + 게임별 락** (0단계 실측 결론, [`api/games/maze.md`](api/games/maze.md) §8)
2. 워커 간 브로드캐스트를 Redis Pub/Sub으로 (WebSocket 객체 자체는 본질적으로
   프로세스 내에 남는다 — 연결 맵은 그대로 두고 메시지 전달만 Pub/Sub)
3. **1:1:1 지원 — 게임 엔진 N인 일반화**

   `len(self._queue) < 2` 하나를 고치는 문제가 아니다. **엔진 전반이 2인 전제**다.
   설계 원칙은 [`api/platform.md`](api/platform.md) §5 "확장성 원칙" 참조.

   | 파일 | 대상 |
   | :--- | :--- |
   | `core/board.py` | `PLAYER1_START`/`PLAYER2_START`, `PLAYER1_GOAL_ROW`/`PLAYER2_GOAL_ROW` → **모드별 배치 테이블**(`duel`=변 중앙 대향 2점, `trio`=네 꼭짓점 중 랜덤 3, `quad`(미래)=네 꼭짓점 전부) |
   | `core/player.py` | `player_id not in (1,2)` 예외, `create_player1`/`create_player2`, `goal_row` 단일 축 → `seat_no` + **`goals[]` 목록**(축+값), **`eliminated`·`eliminated_order`** 추가 |
   | `core/game_state.py` | `player1`/`player2` 속성 → 좌석 목록, `current_turn = 2 if … == 1 else 1` → 순환, `PLAYER1_WIN`/`PLAYER2_WIN` → `winner_seat_no`, `to_dict()` 의 `"player1"`/`"player2"` 키, 종료 판정에 **`last_standing`**(생존자 1명) 추가 |
   | `core/move_validator.py` | **작업이 줄었다** — 점프 로직(`_get_jump_moves`) 삭제 + `opponent` 인자 **제거**. 상대 목록이 필요 없다 ([`api/games/maze.md`](api/games/maze.md) §5) |
   | `core/pathfinder.py` | `player1_pos`/`player1_goal` 2인 전용 서명 → **생존자 목록** (탈락자를 포함하면 벽 설치가 영구 거절된다). `other_player_pos` 인자는 **삭제** — 말이 경로를 막지 않는다 (§5) |
   | `ai/simple_ai.py` | `game_state.opponent_player` 단일 상대 전제 |
   | `serializers/game_serializer.py` | `player1_name`/`player2_name` |
   | `db/models.py` | `player1_*`/`player2_*` → `game_participants` + `seat_no` |

   > 판단 기준: **"인원이 4명이 되면 무엇을 고쳐야 하는가?"** 행 추가 외에
   > 스키마·코드 변경이 필요하면 아직 하드코딩이 남은 것이다.
4. `match_queue`·`game_rooms` **테이블**과 in-process dataclass의 권위 경계 정리 —
   **완료.** 테이블은 2단계, in-process `room_manager`·`matchmaking` 은 3단계에서 폐기했고
   권위는 Redis 다 ([`api/platform.md`](api/platform.md) "Redis 키 스키마")
5. maze WS 라우터를 `main.py`에 등록 — 7단계에서 §12 핸들러를 **새로 작성**한 뒤 등록한다
   (구 `app/ws/ws_game.py` 는 3단계에서 삭제했다)
6. **시야 엔진** — 3×3 차폐 판정 + 변 단위 `visible_edges` + 플레이어별 누적
   상태(`discovered_edges`·`last_seen_players`)를 Redis에 게임 수명 동안 보관
   ([`api/games/maze.md`](api/games/maze.md) §6)
7. **시간 체계** — Fischer 게임 시계 + 접속 시계 분리 + Redis ZSET 스위퍼 +
   배포 시 서버 유예 + Redis 상태 유실 시 무효 처리 ([`api/games/maze.md`](api/games/maze.md) §8)

**실행 순서** — 계획서 [`plans/2026-10-01-M3-착수순서.md`](plans/2026-10-01-M3-착수순서.md).
실측 보고서 [`research/2026-10-01-워커-redis-실측.md`](research/2026-10-01-워커-redis-실측.md).

| 단계 | 내용 | 위 작업 | 선행 |
| :--- | :--- | :--- | :--- |
| 0 ✅ | 워커·Redis 동작 실측 → 게임 상태 모델 결정 → maze.md §8 개정 | (신설) | — |
| 1 ✅ | 구 REST `/api/v1/quoridor/*` 폐기 + 엔진 N인 일반화 (`core/*`, `ai`, `serializers`) | 3 (엔진) | — |
| 2 ✅ | `db/models.py` 정리 — `game_participants`+`seat_no`, `match_queue`·`game_rooms` 폐기, `daily_champions`·스케줄러·`apscheduler` 제거 | 3 (DB) + 4 | 1 |
| 2.5 ⏸ | **역할별 독립 분석 (코드 변경 없음) — 보류** — 게임 리뷰어 → 스키마 최적화 → 악의적 공격자 → 클린 코드. 산출물은 `docs/research/` 보고서 + 제안별 채택 결정표. 채택 항목이 3단계 이후 계획서의 입력이 된다 | (신설) | 2 |
| 3 ✅ | 큐·방·게임 상태를 Redis로 — 처음부터 `players[]`/`seat_no` 스키마. 구 `ws_game`·`room_manager`·`matchmaking`·`quoridor_service` 삭제 | 1 | 0, 1, 2 |
| 4 ✅ | 워커 간 전달을 Pub/Sub으로 — 서비스가 상태를 쓴 직후 발행, 워커당 패턴 구독 1개 + 재구독 후 재동기화, `connection_manager` 는 연결 맵만 | 2 | 3 |
| 5 ✅ | 시야 엔진 — 3×3 + 벽 차폐(반지름 1.25 원 모델의 이산화), 변 원소에 `wall` 여부, 좌석별 누적 관측 `game:{id}:vision:{seat_no}` 를 state 와 한 번의 펜싱 쓰기로, 탈락 좌석 동결 + 친구 방 관전 패킷 | 6 | 1, 3 |
| 6 | 시간 체계 | 7 | 0, 4 |
| 7 | **maze WS 핸들러(§12) 신규 작성**(3단계 서비스 대상) + `main.py` 라우터 등록 + 구독 버스 lifespan 배선 + `--workers 2` 완료 판정. **실제 다중 프로세스 확인 포함** — 4단계는 한 프로세스 안에 버스 2개를 띄워 흉내 냈을 뿐이다. 아래 "완료 판정" 참조 | 5 | 전부 |

> 작업 3(엔진)이 작업 1·4보다 먼저다. 좌석 모델(`seat_no`, `goals[]`, `eliminated`)이
> Redis 키 스키마와 DB 스키마 양쪽의 입력이기 때문이다. 뒤에 하면 둘 다 2인용으로
> 만들었다가 다시 만든다.

> **2.5단계를 3단계 앞에 두는 이유:** 3단계부터 Redis 키 스키마·게임별 락·WS 프로토콜처럼
> 되돌리기 비싼 설계를 굳힌다. 그 전에 규칙(게임 리뷰어)이 바뀌면 스키마·보안·코드가
> 전부 따라 바뀌므로 상류부터 순서대로 검증한다. 분석 대상은 **남는 코드**(엔진·`db/`·
> `core/`·Redis 계층·레이트 리미터)와 **앞으로 구현할 설계 문서**(maze.md·platform.md)로
> 한정한다 — 교체 예정인 `/users/*`·`/ranking/*`·`memory_store`·`ws_game`·`quoridor_service`
> 를 분석하면 이미 아는 결론만 쌓인다. 역할마다 별도 에이전트로 독립 분석한다
> (2026-10-02 사용자 결정).

> **2.5단계 보류 — 3단계는 2.5 없이 진행한다 (2026-10-02 사용자 결정).** 역할 1 자가대전
> 실측이 실행 비용 미계획으로 중단됐다([계획서](plans/2026-10-02-M3-2.5단계-역할별분석.md)
> "보류 — 재개 조건"). 7단계까지 끝내 실제 게임 동작을 먼저 확인하는 쪽을 택했다. 그
> 대가로 3단계 Redis 스키마·락·WS 프로토콜은 규칙·보안 검증 없이 굳는다 — 이후 문제가
> 드러나면 **교체·수정으로 대응**한다. 단, 단계마다 테스트 전체 통과는 그대로 지킨다
> (망가진 채로 진행하지 않는다). 2.5단계는 7단계 이후 재개를 검토한다.

**완료 판정:** `server/Dockerfile` prod의 `--workers`를 2 이상으로 올리고
매칭이 정상 동작해야 한다. 현재 `Dockerfile:120`에서 `1`로 고정되어 있고,
그 이유가 바로 이 마일스톤이다.

7단계에서 **실제 uvicorn 워커 2개**로 아래를 확인한다(4단계 테스트는 한 프로세스 안의 버스 2개였다):

- 좌석들이 서로 다른 워커에 붙은 상태에서 매칭·방·게임 이벤트가 전원에게 좌석별 내용으로 간다
  (어느 워커에 붙었는지는 E1 처럼 응답의 pid 로 판별한다)
- 한 워커의 구독 연결만 `CLIENT KILL ID` 로 끊으면, 그 워커만 재구독하고 소켓 전원이 재동기화를 받는다
- 한 워커를 죽여도 다른 워커에 붙은 좌석의 게임이 이어지고, 재접속하면 상태가 복원된다

7단계 핸들러가 지켜야 할 것 — 5단계(시야)가 서비스에 남긴 경계([계획서](plans/2026-10-02-M3-5단계-시야엔진.md) "시야 밖 정보가 새는 경로"):

- **`user_id` 는 인증된 연결에서만 꺼낸다.** 페이로드의 좌석·유저 값을 읽지 않는다 — 좌석은 서비스가 `meta.seat_of(user_id)` 로 정한다. `eliminate(seat_no)` 는 스위퍼 전용이라 소켓 메시지에 연결하지 않는다
- **`ActionOutcome.state` 를 소켓에 보내지 않는다.** 전체 상태다. 응답·브로드캐스트는 `game_view` 로만
- **예외 문구를 클라이언트에 보내지 않는다.** 엔진 `ValueError` 문구에 좌표가 있다. §13 코드만 보낸다
- 탈락자의 발신(`chat` 포함) 차단, 탈락 후 나가기(activity 해제 — 결과는 종료 시 그대로 기록), 방장의 시작 전 `allow_spectate` 변경, `game_end.full_board`

### M4 — 리버스 프록시 + E2E 서비스 흐름 검증

**선행 조건:** M3.

로컬·CI·배포가 **동일한 서비스 흐름**을 타도록 Caddy를 앞단에 둔다. 목적은
상용에서만 드러나는 버그를 로컬에서 재현 가능하게 만드는 것이다.

작업:

1. Caddy 리버스 프록시 — 로컬·CI·배포가 동일 Caddyfile 사용
2. WebSocket upgrade가 프록시를 통과하는지 검증
3. `X-Forwarded-For` 기반 레이트 리미팅 검증 — 프록시 뒤에서 `get_remote_address`가
   프록시 IP를 보면 **모든 사용자가 하나의 제한을 공유**한다.
   prod CMD의 `--proxy-headers --forwarded-allow-ips *`가 교정하지만 실측이 필요하다
4. 다중 워커 환경에서 매칭·리미팅 정확성 E2E 검증
5. 프로덕션 CORS 오리진 제한 (아래 TODO)

---

## 미해결 TODO

착수 시점이 정해지지 않은 항목. 발견 경위와 판단 근거를 함께 남긴다.

| 항목 | 내용 | 비고 |
| :--- | :--- | :--- |
| Alembic 도입 | 스키마 생성이 `app/db/config.py` 의 `create_all` 뿐이다. `create_all` 은 기존 테이블을 바꾸지도 지우지도 않아 스키마 변경 시 DB 를 손으로 리셋해야 한다(M3 2단계에서 개발 DB 를 1회 리셋했다) | **첫 운영 배포 전 필수.** 지금 도입하지 않은 이유: 운영 DB·보존할 데이터가 없고, `users` 가 인증 작업에서 다시 전면 개편된다 — 베이스라인을 지금 만들면 곧 다시 쓴다 (2026-10-02 사용자 결정) |
| CORS 오리진 제한 | `app/main.py:96`이 `allow_origins=["*"]` | 개발 편의. **프로덕션 배포 전 필수**. M4에서 처리 |
| WS 라우터 미등록 | maze WS 라우터가 아직 없다. 구 Quoridor 핸들러 `app/ws/ws_game.py` 는 M3 3단계에서 삭제했다 | 의도적. M3 7단계에서 §12 핸들러를 새로 작성해 `main.py` 에 등록하고, 구독 버스(`app/ws/bus.py`) start/stop 도 lifespan 에 함께 건다. 현황은 `app/ws/__init__.py` docstring |
| CI 비밀번호 생성 단계 첫 실행 확인 | `test-and-merge.yml` server-tests 잡의 `Generate Redis password` 단계(커밋 `e39b806`, compose 비밀번호 기본값 제거)가 아직 한 번도 실행되지 않았다. 워크플로가 `dev-test` push 에서만 돈다 | **재구조화 완료 후 첫 `dev-test` push 때** 확인한다 — 잡 통과, 로그에 비밀번호가 마스킹됨, `docker compose` 가 `:?` 필수값 오류 없이 뜸. 로컬에서는 같은 조건(무작위 비밀번호 + 필수값)으로 확인했다 |
| 스케줄러 제거 판단 | `app/services/scheduler/`는 일일 리셋 전용이고, 랭킹이 MMR로 단순화되면 쓰이지 않는다 | **완료**(M3 2단계, 커밋 `3e889a9`). 근거 3개: ① 시계 만료를 ZSET 스위퍼가 처리한다 ② `refresh_tokens` 정리가 주기 작업을 쓰지 않는다 ③ `daily_champions` 폐기로 `daily_reset.py`의 유일한 용도가 소멸한다 → `app/services/scheduler/`와 `apscheduler==3.10.4` 제거, `uv.lock` 재생성(전이 의존성 `pytz`·`tzdata`·`tzlocal` 동반 제거) |

---

## 향후 확장 (애자일)

시스템이 안정된 뒤 재검토한다. 지금 설계에 넣지 않되, **설계가 이 확장을
막지 않도록** 둔다.

- **데일리 점수·시즌 랭킹** — 랭킹을 MMR 하나로 단순화하면서 일일 리셋 점수판과
  `daily_champions`를 폐기했다. 가벼운 경쟁 요소가 필요해지면 MMR 기록의
  시간축을 활용해 다시 얹는다
- **리플레이·수 기록** — 2026-10-01에 폐기했다(엔드포인트 5개, `game_moves`,
  `game_state_snapshot`, `game_sessions.game_history`, `GameSerializer`의 리플레이
  부분, 테스트 11개). 복원이 필요하면 **커밋 `2a56fa9` 에서 꺼낸다.**
  재도입 시 Fog of War 정책(전체 공개 vs 플레이어 시점 재생)과 함께, **이동
  경로·수 기록을 `game_end.full_board`와 함께** 설계한다 — 지금 `full_board`는
  최종 상태만 담고 경로·수 기록은 담지 않는다
- **MMR 매칭 범위 제한** — Phase 1은 매칭에 MMR 필터를 걸지 않는다(출시 직후
  동시 접속자가 적어 필터를 걸면 매칭이 성사되지 않는다). 큐 인구가 확보된
  뒤 서버 설정으로 켠다 ([`api/games/maze.md`](api/games/maze.md) §3)
- 나머지 5종 게임 API — `docs/api/games/`에 `maze.md`와 동일한 틀로 추가

---

## 관련 문서

| 문서 | 내용 |
| :--- | :--- |
| [`PLATFORM_ARCHITECTURE.md`](../PLATFORM_ARCHITECTURE.md) | 단일 기준 문서(SSOT). 기술 스택, 보안 원칙, 게임 6종 명세, 디렉토리 구조 |
| [`CLAUDE.md`](../CLAUDE.md) | 개발 명령, 계층별 책임, 진행 상태, 버전 고정 정책 |
| [`api/platform.md`](api/platform.md) | 플랫폼 공통 API — 인증, 계정 병합, 프로필, MMR |
| [`api/games/maze.md`](api/games/maze.md) | 1인칭 미로 API — WebSocket 프로토콜, Fog of War |
| [`환경.md`](환경.md) | 개발 환경 구성과 트러블슈팅 |
| [`plans/`](plans/README.md) | 계획서 보관소. 완료된 계획의 결정 근거·이탈 기록 |
