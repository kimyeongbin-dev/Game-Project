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

두 축은 독립이다. 현재 위치는 **출시 `Phase 1`(Android) 진행 중 + 인프라 `M2` 완료**다.

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

**선행 조건:** `docs/api/games/maze.md` 확정. 설계 없이 착수하면 1:1:1 확장 때 다시 뒤집힌다.

> ⚠️ **아직 남았다 — 아래 "maze.md 잔여 설계 3건"을 먼저 닫는다.**
> 미결 표는 비웠지만 **이동 규칙 본문이 없다.** 그 상태로 착수하면 작업 3의
> `core/move_validator.py` 에서 막힌다.

현재 `app/ws/`의 상태가 전부 프로세스 내 모듈 전역 dict다
(`connection_manager._connections`, `matchmaking._queue`, `room_manager._rooms`).
`PLATFORM_ARCHITECTURE.md` §2.2는 Redis 8이 매치메이킹 큐·실시간 방 상태·
게임 시계와 접속 유예 데드라인·Pub/Sub을 전담하도록 규정한다.

작업:

1. 매치메이킹 큐·방 상태를 Redis로 이전
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
   | `core/move_validator.py` | 단일 `opponent: Player` → 상대 **목록** (점프 규칙이 3인에서 달라진다) |
   | `core/pathfinder.py` | `player1_pos`/`player1_goal` 2인 전용 서명 → **생존자 목록** (탈락자를 포함하면 벽 설치가 영구 거절된다) |
   | `ai/simple_ai.py` | `game_state.opponent_player` 단일 상대 전제 |
   | `serializers/game_serializer.py` | `player1_name`/`player2_name` |
   | `db/models.py` | `player1_*`/`player2_*` → `game_participants` + `seat_no` |

   > 판단 기준: **"인원이 4명이 되면 무엇을 고쳐야 하는가?"** 행 추가 외에
   > 스키마·코드 변경이 필요하면 아직 하드코딩이 남은 것이다.
4. `match_queue`·`game_rooms` **테이블**과 in-process dataclass의 권위 경계 정리.
   현재 같은 개념이 두 곳에 병존한다 (`app/db/models.py:115,150` vs
   `app/ws/room_manager.py:37,80`)
5. `app/ws/ws_game.py` 라우터를 `main.py`에 등록 (지금은 의도적으로 미등록)
6. **시야 엔진** — 3×3 차폐 판정 + 변 단위 `visible_edges` + 플레이어별 누적
   상태(`discovered_edges`·`last_seen_players`)를 Redis에 게임 수명 동안 보관
   ([`api/games/maze.md`](api/games/maze.md) §6)
7. **시간 체계** — Fischer 게임 시계 + 접속 시계 분리 + Redis ZSET 스위퍼 +
   워커 하트비트/무효 처리 ([`api/games/maze.md`](api/games/maze.md) §8)

**완료 판정:** `server/Dockerfile` prod의 `--workers`를 2 이상으로 올리고
매칭이 정상 동작해야 한다. 현재 `Dockerfile:120`에서 `1`로 고정되어 있고,
그 이유가 바로 이 마일스톤이다.

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

## maze.md 잔여 설계 3건 — **다음 세션 / M3 선행**

2026-10-01에 미결 15건을 확정(커밋 `e8af2d6`)했으나, 그 직후 점검에서 **제기된
적이 없어 미결 표에 오르지도 못한** 구멍 2개가 드러났다. `maze.md` 의 미결 표가
"현재 미결 없음"이라고 말하는 것은 **지금 사실이 아니다.**

**플랜 모드로 사용자와 디테일을 맞춰가며 진행한다.** 아래 ①이 설계 판단이 많아
혼자 확정하지 않는다.

### ① 이동 규칙 본문 신설 (§5) — M3 를 직접 막는다

현재 §5 "이동"은 payload 스키마 3줄(`row`, `col`)이 전부다. **"어느 칸으로 갈 수
있는가"가 설계서 어디에도 없다.** §13 에 `invalid_move | 이동 규칙 위반` 코드만
있고 그 "규칙"의 본문이 없다. §7(벽 설치)이 검증 순서를 4단계로 명시한 것과
비대칭이다.

특히 **점프 규칙**: 설계서 전체에서 `점프` 는 **1회**만 등장하며, 그것도 §11
"왜 2인은 변 중앙인가" 표의 근거 문장에서 스쳐 지나간다. 정의가 없다.
그런데 아래 M3 작업 3의 `core/move_validator.py` 행은 **"점프 규칙이 3인에서
달라진다"**고 못박았다 — 달라진다는 것은 아는데 어떻게 달라지는지가 없다.

맞춰야 할 것:

| 쟁점 | 내용 |
| :--- | :--- |
| 기본 이동 | 직교 인접 1칸. 벽·보드 경계로 막히지 않을 것 |
| 점프 (2인) | 인접 상대를 뛰어넘는다. 뒤에 벽이 있으면 대각 우회 |
| 점프 (3인 이상) | **말 둘이 연달아 붙어 있으면?** 연쇄 점프 허용 여부 |
| | **점프 착지점에 세 번째 말이 있으면?** |
| | **대각 우회가 양쪽 다 가능하면?** 둘 다 허용 / 선택 강제 |
| 탈락자의 말 | 보드에 남아 장애물로 취급한다(§9). **점프 대상이 되는가** |
| **Fog of War 상호작용** | 상대가 **내 시야 밖이면 클라이언트는 점프 가능 여부를 계산할 수 없다.** §7 "유효 수 목록을 서버가 주지 않는다"와 정면으로 만난다. 서버가 거절로만 답할지, 거절이 §7 처럼 **의도된 추리 정보**인지, 턴당 횟수 제한을 걸지 결정해야 한다 |
| 승리 판정 | `goals[]` 중 **아무 칸**에 도달하면 승리인지 명문화 (§11 의 L자 17칸) |

> 재사용: `server/app/games/maze/core/move_validator.py` 에 2인 전제 구현이
> 이미 있다. **규칙을 새로 발명하기 전에 현행 구현을 먼저 읽는다.**

### ② 온라인 AI 좌석을 §1 에 반영 — 문서 불일치

[`platform.md`](api/platform.md) §6 은 "온라인 AI 좌석은
`game_participants.is_ai = true` 로 멀티 프로토콜을 그대로 재사용하고 서버
엔진(`simple_ai.py`)이 둔다(MMR 미반영)"로 확정했다. 그런데 `maze.md` §1 은
여전히 "솔로(AI 대전)는 100% 오프라인 / 클라이언트 AI 는 Dart" 만 말한다 —
`maze.md` 에 `is_ai` 검색 **0건**이다. 두 문서가 어긋난다.

### ③ 미결 표 정정

`maze.md` 말미의 "**현재 미결 없음.**" 을 위 ①②로 교체한다. ①을 확정하면
"확정된 항목" 표로 옮긴다.

> **왜 이 절이 TODO 표가 아니라 여기 있는가:** 착수 시점이 미정인 항목이 아니라
> **M3 의 선행 조건**이다. 그리고 `maze.md` 가 스스로 "미결 없음"이라 말하고
> 있으므로, 그 문서만 읽고 M3 에 착수하는 것을 막을 기록이 여기 있어야 한다.

---

## 미해결 TODO

착수 시점이 정해지지 않은 항목. 발견 경위와 판단 근거를 함께 남긴다.

| 항목 | 내용 | 비고 |
| :--- | :--- | :--- |
| `utcnow` 일원화 | `app/core/time.py`에 표준 헬퍼가 있으나, 동일한 로컬 헬퍼가 3곳에 중복 정의되어 있다 — `app/db/models.py:20`, `app/games/maze/core/game_state.py:22`, `app/services/quoridor_service.py:24` | 동작에는 문제 없음. 정리는 해당 파일을 손댈 때 함께 |
| CORS 오리진 제한 | `app/main.py:96`이 `allow_origins=["*"]` | 개발 편의. **프로덕션 배포 전 필수**. M4에서 처리 |
| WS 라우터 미등록 | `app/ws/ws_game.py`가 `main.py`에 등록되어 있지 않다 | 의도적. 구 Quoridor 프로토콜이며 §4.1 재설계 대기. 동작하는 기능으로 오인되지 않게 하려는 것. 판정 내역은 `app/ws/__init__.py` docstring |
| 스케줄러 제거 판단 | `app/services/scheduler/`는 일일 리셋 전용이고, 랭킹이 MMR로 단순화되면 쓰이지 않는다 | **결정 완료.** 근거 3개: ① 시계 만료를 ZSET 스위퍼가 처리한다 ② `refresh_tokens` 정리가 주기 작업을 쓰지 않는다 ③ `daily_champions` 폐기로 `daily_reset.py`의 유일한 용도가 소멸한다 → **M3에서 `app/services/scheduler/`와 `apscheduler==3.10.4` 제거**(`uv.lock` 재생성 포함) |

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
