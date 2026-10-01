# 플랫폼 공통 API 설계서

> **대응 명세:** [`PLATFORM_ARCHITECTURE.md`](../../PLATFORM_ARCHITECTURE.md) §1.1 (하이브리드 플레이),
> §3.2 (하드웨어 금고), §3.3 (데이터 신뢰 분리)
>
> **범위:** 인증, 계정 병합, 프로필, 전적·MMR. 게임별 API는 [`games/`](games/)에 있다.
>
> **상태:** 설계 확정 전. 구현은 이 문서 승인 후 시작한다.
> 현재 서버에 있는 `/api/v1/users`·`/api/v1/ranking`은 구 Quoridor 기준이며
> **이 설계로 교체된다** (§6 참조).

---

## 목차

- [§0 공통 규약](#0-공통-규약)
- [§1 인증](#1-인증)
- [§2 계정 병합](#2-계정-병합)
- [§3 프로필](#3-프로필)
- [§4 전적과 MMR](#4-전적과-mmr)
- [§5 데이터 모델 영향](#5-데이터-모델-영향)
- [§6 폐기 대상과 대체 경로](#6-폐기-대상과-대체-경로)

---

## §0 공통 규약

### Base URL과 버저닝

```
https://<host>/api/v1
```

경로 기반 버저닝. 호환을 깨는 변경은 `/api/v2`를 신설하고 `/api/v1`을 유지한다.
필드 **추가**는 호환을 깨지 않으므로 버전을 올리지 않는다.

### 성공 응답

```json
{
  "success": true,
  "data": { }
}
```

페이로드는 항상 `data` 안에 넣는다. 최상위에 펼치지 않는다 — 기존
`/api/v1/users`가 `user_id`·`nickname`·`score`를 최상위에 펼쳐 두어
응답마다 구조가 달랐고, 클라이언트가 엔드포인트별로 파싱을 다르게 해야 했다.

### 실패 응답

```json
{
  "success": false,
  "error": "invalid_token",
  "message": "로그인이 만료되었습니다. 다시 로그인해주세요.",
  "detail": "token expired at 2026-10-01T00:00:00Z"
}
```

| 필드 | 용도 |
| :--- | :--- |
| `error` | 기계 판독용 코드. `snake_case` |
| `message` | **사용자에게 그대로 보여줄 한국어.** 클라이언트가 코드별 문구를 따로 관리하지 않게 한다 |
| `detail` | 개발자용 상세. 선택. 민감 정보를 넣지 않는다 |

> 이 형태는 **현행 레이트 리미터 구현과 일치**한다
> (`server/app/middleware/rate_limiter.py`). 리미터의 429는 전역 미들웨어가
> 생성하므로 엔드포인트가 형태를 바꿀 수 없다. 따라서 **전체 API가 이 형태를
> 따라야** 응답 규약이 하나로 유지된다.

### HTTP 상태 코드

| 코드 | 사용 |
| :--- | :--- |
| 200 | 조회·갱신 성공 |
| 201 | 생성 성공 |
| 204 | 성공, 본문 없음 (로그아웃 등) |
| 400 | 요청 형식·값 오류 |
| 401 | 인증 없음/만료/무효 |
| 403 | 인증됐으나 권한 없음 |
| 404 | 대상 없음 |
| 409 | 상태 충돌 (닉네임 중복, 이미 병합됨) |
| 422 | 스키마 검증 실패 (FastAPI 기본) |
| 429 | 레이트 리미트 초과 |
| 500 | 서버 오류. `detail`에 내부 정보를 노출하지 않는다 |

### 에러 코드

도메인 접두어 없이 평면적으로 쓴다. 중복될 때만 접두어를 붙인다.

| 코드 | 상태 | 의미 |
| :--- | :--- | :--- |
| `invalid_request` | 400 | 요청 형식 오류 |
| `unauthorized` | 401 | 인증 헤더 없음 |
| `invalid_token` | 401 | 토큰 무효·만료 |
| `token_reuse_detected` | 401 | 폐기된 리프레시 토큰 재사용 (§1.4) |
| `kakao_verification_failed` | 401 | 카카오 ID Token 검증 실패 |
| `forbidden` | 403 | 권한 없음 |
| `not_found` | 404 | 대상 없음 |
| `nickname_taken` | 409 | 닉네임 중복 |
| `nickname_invalid` | 400 | 닉네임 규칙 위반 |
| `already_merged` | 409 | 이미 병합된 계정 (§2) |
| `merge_not_applicable` | 409 | 병합 조건 불충족 (§2.3) |
| `feature_disabled` | 400 | 현 Phase 범위 밖 기능 (예: `chat` — [`games/maze.md`](games/maze.md) §12) |
| `rate_limit_exceeded` | 429 | 레이트 리미트 |
| `internal_error` | 500 | 서버 오류 |

### 인증 헤더

```
Authorization: Bearer <access_token>
```

### 레이트 리미트

기본 **분당 60회 / 클라이언트 IP**. `RATE_LIMIT_PER_MINUTE`로 조정한다.
카운터는 Redis 논리 DB 2에 저장되어 워커·인스턴스 수와 무관하게 정확하다.

초과 시 — **아래 형태는 현행 구현 실측값이다. 변경하지 않는다.**

```
HTTP/1.1 429 Too Many Requests
Retry-After: 60
Content-Type: application/json
```

```json
{
  "success": false,
  "error": "rate_limit_exceeded",
  "message": "요청이 너무 많습니다. 잠시 후 다시 시도해주세요.",
  "detail": "60 per 1 minute",
  "retry_after": 60
}
```

> `retry_after`(본문)와 `Retry-After`(헤더)를 모두 보낸다.
> 근거 구현: `server/app/middleware/rate_limiter.py`,
> 고정 테스트: `server/tests/api/test_rate_limit.py`

프록시 뒤에서는 `X-Forwarded-For`가 반영되어야 실제 클라이언트별로 제한된다.
그렇지 않으면 **모든 사용자가 하나의 제한을 공유**한다. prod 실행에
`--proxy-headers --forwarded-allow-ips *`가 있으며, 프록시 경유 실측은
인프라 마일스톤 M4에서 수행한다 ([`../ROADMAP.md`](../ROADMAP.md)).

### 목록 응답과 페이지네이션

커서 기반을 쓴다. 리더보드처럼 순위가 바뀌는 목록에서 offset은 항목 누락·중복을
일으킨다.

```
GET /api/v1/leaderboard?limit=20&cursor=<opaque>
```

```json
{
  "success": true,
  "data": {
    "items": [ ],
    "next_cursor": "eyJtbXIiOjE0MjAsImlkIjo5OX0",
    "has_more": true
  }
}
```

`limit` 기본 20, 최대 100. `next_cursor`는 불투명 문자열이며 클라이언트가
해석하지 않는다. `has_more`가 `false`면 `next_cursor`는 `null`이다.

### 시간 형식

ISO 8601, UTC, `Z` 접미사. 예: `2026-10-01T09:30:00Z`

> 현행 코드는 **naive UTC + `Z` 접미사** 직렬화를 전제한다
> (`server/app/core/time.py`의 `utcnow()` docstring 참조). DB의 `DateTime`
> 컬럼도 timezone-naive다. 이 전제를 바꾸려면 직렬화와 컬럼을 함께 고쳐야 한다.

### 멱등성

`POST`가 재시도로 중복 실행되면 안 되는 경우(계정 병합) 서버가 멱등성을
보장한다. 방식은 §2.4에 기술한다.

---

## §1 인증

### 설계 원칙

§1.1의 하이브리드 플레이 모델을 그대로 따른다.

| 상태 | 로그인 | 가능한 것 |
| :--- | :--- | :--- |
| **익명** | 불필요 | 솔로 플레이 전체. 100% 오프라인 |
| **카카오 연동** | 필수 | 멀티플레이, 콘텐츠 공유, MMR |

두 상태 모두 **서버 접근 시에는 JWT를 쓴다.** 익명이라고 인증이 없는 것이
아니라, "카카오 신원이 없는 계정"으로 취급한다. 그래야 서버 측 인증 코드가
하나로 유지된다.

### §1.1 익명 계정 생성

앱 최초 실행 시 클라이언트가 UUID v4를 생성해 **하드웨어 금고**
(Android Keystore / iOS Keychain)에 보관하고, 서버에 등록해 토큰을 받는다.

```
POST /api/v1/auth/anonymous
```

```json
{ "device_key": "3f2b1c90-7a44-4e8d-9b12-0c5a8e2f1d77" }
```

```json
{
  "success": true,
  "data": {
    "access_token": "<jwt>",
    "refresh_token": "<jwt>",
    "token_type": "Bearer",
    "expires_in": 1800,
    "user": {
      "id": 1042,
      "auth_type": "anonymous",
      "nickname": null
    }
  }
}
```

- `device_key`는 **클라이언트가 생성**한다. 서버가 발급하지 않는다 —
  §3.2의 "앱 최초 실행 시(오프라인 상태 가능) 기기 내부에서 생성" 요구 때문이다.
  오프라인에서 솔로를 시작한 뒤 나중에 온라인이 되어 등록할 수 있어야 한다.
- 같은 `device_key`로 다시 호출하면 **기존 계정의 새 토큰**을 반환한다 (멱등).
- 익명 계정은 닉네임이 없다 (`null`). 닉네임은 멀티플레이 진입 시 필요하다.

> **보안 판단:** `device_key`만으로 인증되므로 키가 유출되면 그 익명 계정을
> 탈취할 수 있다. 그러나 익명 계정에는 **솔로 데이터만** 있고 전적·MMR·재화가
> 없다(§3.3 원칙 1·2). 하드웨어 금고 보관으로 일반적인 유출은 차단되며,
> 남는 위험이 타 유저나 서버 생태계에 영향을 주지 않으므로 이 수준을 수용한다.
> 멀티플레이 자산은 카카오 신원에만 귀속된다.

### §1.2 카카오 로그인

클라이언트가 카카오 SDK로 로그인해 **ID Token(OIDC)** 을 얻고 서버에 전달한다.
서버는 카카오 공개키(JWKS)로 서명·`iss`·`aud`·`exp`를 검증한 뒤 토큰을 발급한다.

```
POST /api/v1/auth/kakao
```

```json
{ "id_token": "<kakao id token>" }
```

응답은 §1.1과 동일한 구조이며 `auth_type`이 `"kakao"`다.

- 서버는 ID Token의 `sub`를 계정 키로 저장한다. **닉네임·프로필 이미지 등
  클라이언트가 보낸 값은 신뢰하지 않는다** — 위조 가능하다. 필요하면 서버가
  카카오 API로 직접 조회한다.
- 신규 `sub`면 계정을 생성하고, 기존 `sub`면 로그인 처리한다.
- `Authorization` 헤더에 **익명 access token을 함께 보내면 계정 병합을 시도**한다
  (§2).

> **MUST NOT:** 액세스 토큰(`access_token`)만 받아서 카카오 사용자 정보 API로
> 신원을 확인하는 방식은 쓰지 않는다. ID Token 검증이 표준이며, 토큰 대상
> (`aud`)이 우리 앱인지 확인할 수 있어 토큰 오용을 막는다.

### §1.3 토큰 구조

| 클레임 | 값 |
| :--- | :--- |
| `sub` | 내부 `user_id` (문자열) |
| `typ` | `access` \| `refresh` |
| `auth` | `anonymous` \| `kakao` |
| `jti` | 토큰 고유 ID (리프레시 회전 추적용) |
| `iat`, `exp` | 발급·만료 (UTC epoch) |

| 토큰 | 수명 | 저장 위치 |
| :--- | :--- | :--- |
| access | 30분 | 메모리 (디스크에 쓰지 않음) |
| refresh | 30일 | 하드웨어 금고 |

`typ`을 반드시 검증한다. 리프레시 토큰을 액세스 토큰 자리에 쓰는 것을 막는다.

### §1.4 토큰 갱신과 폐기

```
POST /api/v1/auth/refresh
```

```json
{ "refresh_token": "<jwt>" }
```

**리프레시 토큰 회전(rotation)을 적용한다.** 갱신 시 기존 리프레시 토큰을
폐기하고 새 쌍을 발급한다. 폐기된 토큰이 다시 사용되면 **탈취로 간주해 해당
사용자의 모든 리프레시 토큰을 폐기**하고 `token_reuse_detected`(401)를 반환한다.
클라이언트는 이 코드를 받으면 재로그인 화면으로 보낸다.

```
POST /api/v1/auth/logout      # 204
```

호출자의 리프레시 토큰을 폐기한다. 액세스 토큰은 만료까지 유효하다 — 짧은
수명(30분)으로 이를 수용한다. 즉시 차단이 필요하면 `jti` 블랙리스트를 Redis에
두는 방식을 추가할 수 있으나, 현 요구에는 과하다.

---

## §2 계정 병합

### §2.1 원칙 — 이관 대상을 엄격히 한정한다

§3.3 원칙 2의 Zero-Trust를 그대로 구현한다. 클라이언트가 보낸 값 중 **무엇을
받아들일지 허용 목록으로 정의**하고, 목록에 없는 것은 전부 버린다.

**이관 허용 (allowlist)**

| 항목 | 이유 |
| :--- | :--- |
| 솔로 퍼즐 진행도 | 개인 만족형 기록. 조작되어도 타 유저·생태계에 영향 없음 |
| 해금 상태 | 위와 동일 |

**이관 금지 (denylist) — 어떤 경우에도 받지 않는다**

| 항목 | 이유 |
| :--- | :--- |
| 승패·전적 | 멀티플레이 결과는 서버만 기록한다 (§3.3 원칙 2) |
| MMR | 서버가 계산한다. 클라이언트 주장은 의미가 없다 |
| 재화 | 서버 권위 자산 |
| 랭킹·순위 | 서버가 MMR로 도출한다 |

> **MUST NOT:** 클라이언트가 승패·전적·MMR·재화 값을 보내는 엔드포인트를
> 만들지 않는다. 필드가 존재하는 것 자체가 공격면이다.

### §2.2 흐름

```
POST /api/v1/auth/kakao
Authorization: Bearer <익명 access token>      ← 이 헤더가 있으면 병합 시도
```

```json
{
  "id_token": "<kakao id token>",
  "merge": {
    "solo_progress": [
      { "game": "number_ten", "best_score": 1520, "cleared_stages": [1,2,3] },
      { "game": "word_puzzle", "cleared_count": 47, "unlocked_themes": ["idiom","slang"] }
    ]
  }
}
```

응답에 병합 결과를 명시한다.

```json
{
  "success": true,
  "data": {
    "access_token": "<jwt>",
    "refresh_token": "<jwt>",
    "token_type": "Bearer",
    "expires_in": 1800,
    "user": { "id": 2210, "auth_type": "kakao", "nickname": null },
    "merge": {
      "performed": true,
      "merged": ["number_ten", "word_puzzle"],
      "rejected": []
    }
  }
}
```

`rejected`에는 서버가 받아들이지 않은 항목과 이유를 담는다. 조용히 버리지 않는다
— 클라이언트가 로컬 데이터를 지울지 판단해야 한다.

### §2.3 충돌 처리 — 서버가 임의로 합치지 않는다

카카오 `sub`에 해당하는 계정이 **이미 존재하고 그 계정에도 솔로 진행도가 있는**
경우, 서버는 두 진행도를 자동으로 합치지 않는다. `merge.performed: false`와
`merge_not_applicable`을 함께 반환하고 **기존 계정으로 로그인만** 시킨다.

이유: 서버가 "더 진행된 쪽"을 자동 선택하면 유저가 무엇을 잃는지 예측할 수 없다.
어느 쪽을 남길지는 유저가 결정해야 하는 문제이며, 그 UI는 클라이언트가 제공한다.

유저 선택을 받아 재시도하는 병합 API는 **Phase 1 범위 밖**이며 **솔로 플레이
도입 시점에 함께 설계**한다. 설계 후보: `PUT /api/v1/me/solo-progress/{game}`
(전체 교체, 멱등).

> **MUST:** 병합이 거절되면 클라이언트는 **로컬 솔로 진행도를 삭제하지 않는다.**
> 선택 병합 API가 추가될 때 복구할 원본이 사라진다.

### §2.4 멱등성

병합은 계정당 최초 1회만 일어난다. 재시도로 중복 적용되지 않도록:

- `users`에 병합 완료 시각(`merged_at`)을 기록하고, 값이 있으면 `already_merged`(409)
- 병합 원본이 된 익명 계정은 **삭제하지 않고 비활성 처리**한다. 감사와
  중복 병합 차단에 필요하다

---

## §3 프로필

### 내 정보 조회

```
GET /api/v1/me
Authorization: Bearer <access_token>
```

```json
{
  "success": true,
  "data": {
    "id": 2210,
    "auth_type": "kakao",
    "nickname": "미로장인",
    "created_at": "2026-09-01T12:00:00Z",
    "stats": { "mmr": 1042, "wins": 13, "losses": 9, "games": 22, "placement_remaining": 0 }
  }
}
```

익명 계정은 `nickname: null`이고 `stats`가 없다 — 멀티플레이를 하지 않으므로
전적이 존재하지 않는다.

### 닉네임 설정·변경

```
PATCH /api/v1/me
```

```json
{ "nickname": "미로장인" }
```

**규칙:** 2~12자, 영문·숫자·한글. 기존 구현과 동일하게 유지한다
(`server/app/schemas/users.py`의 `min_length=2, max_length=12`).

닉네임은 **멀티플레이 진입 전에 필수**다. 없이 매칭을 시도하면
`nickname_invalid`(400)를 반환한다.

중복 시 `nickname_taken`(409).

### 닉네임 사용 가능 확인

```
GET /api/v1/nicknames/availability?nickname=미로장인
```

```json
{ "success": true, "data": { "nickname": "미로장인", "available": false, "reason": "nickname_taken" } }
```

기존 `GET /api/v1/users/check-nickname/{nickname}`을 대체한다. 닉네임을 경로에서
쿼리로 옮긴 이유: 한글·특수문자가 경로에 들어가면 인코딩 문제가 생기고,
빈 문자열 같은 경계값을 표현할 수 없다.

이 엔드포인트는 **입력 중 호출되므로 레이트 리미트가 걸린다.** 클라이언트는
디바운스(예: 400ms)를 적용한다.

---

## §4 전적과 MMR

### §4.1 서버 권위

> **MUST:** MMR과 전적은 **서버가 계산하고 서버만 기록한다.** 클라이언트는
> 결과를 통보받을 뿐이다. 이는 §3.3 원칙 2의 직접 구현이다.

- 승패 판정은 게임 세션을 관리하는 서버가 한다. 클라이언트가 "내가 이겼다"고
  주장하는 경로는 **존재하지 않는다**
- MMR 변동은 게임 종료 시 WebSocket으로 통보된다 (게임별 문서 참조)
- 오프라인에서 달성했다고 주장하는 전적은 리더보드·매칭에 일절 반영되지 않는다

### §4.2 MMR 산정

#### 분리 단위 — `(game, mode)`

MMR 풀을 **게임과 플레이 방식(모드)의 조합**으로 분리한다.

| 게임 | 모드 | MMR 풀 |
| :--- | :--- | :--- |
| `maze_1p` | `duel` (1:1) | 독립 |
| `maze_1p` | `trio` (1:1:1) | 독립 |
| `gomoku_renju` | `duel` | 독립 |

같은 미로라도 1:1과 1:1:1은 **플레이 방식이 아예 다르다.** 1:1은 상대 하나를
읽는 게임이고, 1:1:1은 두 상대의 상호작용과 어부지리가 개입한다. 한 풀에 두면
한쪽 실력이 다른 쪽 매칭 품질을 망친다.

게임별 분리와 모드별 분리를 **같은 메커니즘**으로 처리한다 — 키가
`(user_id, game, mode)` 하나뿐이므로 게임이 늘어도 모드가 늘어도 스키마·API가
그대로다. 일관성과 모듈화를 동시에 얻는다.

> 새 게임·새 모드를 추가할 때 코드 변경 없이 행만 늘어난다. 모드를 열거형으로
> 하드코딩하지 않는다 (§5 확장성 원칙).

#### 산정식

Elo 기반.

| 항목 | 값 |
| :--- | :--- |
| 초기값 | 1000 |
| 배치(placement) | 최초 10판 |
| 하한 | 100 (그 이하로 내려가지 않음) |
| **K 계수** | **모드별 파라미터** (아래) |

```
E_a = 1 / (1 + 10^((R_b - R_a) / 400))
R_a' = R_a + K * (S_a - E_a)          # S_a: 승 1, 무 0.5, 패 0
```

#### K 계수를 모드별로 둔다

| 모드 | 배치 중 | 배치 후 |
| :--- | :--- | :--- |
| `duel` | 40 | 24 |
| `trio` | 32 | 16 |

`trio`의 K가 낮은 이유: 3인 결과는 쌍별로 분해되어 **한 경기에서 2개의 쌍 결과**가
나오므로, 같은 K를 쓰면 1경기당 변동폭이 `duel`의 약 2배가 된다.

> 초판 설계는 변동량을 **2로 나누어** 정규화했다. 그 조치는 duel과 trio가 같은
> 풀을 공유할 때만 의미가 있다. 풀을 분리한 지금은 **정규화를 삭제하고 K로
> 조절한다** — 모드마다 독립 튜닝이 가능해 더 모듈화된다.

#### 다자전 결과의 Elo 변환

순위를 쌍별 결과로 분해하는 방식은 유지한다. 3인 결과 → 3개 쌍
`(1위,2위) (1위,3위) (2위,3위)` 각각에 위 식을 적용하고, 한 플레이어의 변동은
그가 참여한 쌍들의 변동을 **합산**한다 (나누지 않는다).

공동 순위는 해당 쌍을 무승부(`S=0.5`)로 처리한다.

게임별 순위 판정 규칙(무엇이 1위인가, 동점 처리)은 게임 문서에서 정의한다 —
1인칭 미로는 [`games/maze.md`](games/maze.md) §11.

### §4.3 내 전적

```
GET /api/v1/me/stats
```

```json
{
  "success": true,
  "data": {
    "stats": [
      { "game": "maze_1p", "mode": "duel", "mmr": 1042, "wins": 13, "losses": 9,
        "games": 22, "placement_remaining": 0, "rank": 128 },
      { "game": "maze_1p", "mode": "trio", "mmr": 980, "wins": 3, "losses": 5,
        "games": 8, "placement_remaining": 2, "rank": null }
    ]
  }
}
```

- 항목은 `(game, mode)` 단위다. 플레이한 조합만 반환한다
- 배치 미완료(`placement_remaining > 0`)면 `rank`는 `null`이다
- `rank`는 조회 시점 값이며 실시간으로 변한다

### §4.4 리더보드

```
GET /api/v1/leaderboard?game=maze_1p&mode=duel&limit=20&cursor=<opaque>
```

```json
{
  "success": true,
  "data": {
    "game": "maze_1p",
    "mode": "duel",
    "items": [
      { "rank": 1, "nickname": "미로장인", "mmr": 1820, "wins": 204, "losses": 96 }
    ],
    "next_cursor": "eyJtbXIiOjE4MjAsImlkIjo5OX0",
    "has_more": true
  }
}
```

- **`game`과 `mode` 모두 필수다.** MMR 풀이 조합 단위이므로 통합 리더보드는
  의미가 없다. 둘 중 하나라도 없으면 `invalid_request`(400)
- 배치를 마치지 않은 계정은 노출하지 않는다
- 인증 없이 조회 가능하다 (공개 정보). 단 레이트 리미트는 적용된다

> 일일 리셋 점수판과 "어제의 챔피언"은 **이 설계에 포함하지 않는다.** 랭킹
> 개념을 MMR 하나로 단순화했다. 가벼운 경쟁 요소가 필요해지면 MMR 기록의
> 시간축을 활용해 나중에 얹는다 ([`../ROADMAP.md`](../ROADMAP.md) 향후 확장).

---

## §5 데이터 모델 영향

현 `server/app/db/models.py`와 대조한 변경 목록이다.

> **권위:** 데이터 모델의 정본은 이 절과 `server/app/db/models.py`뿐이다.
> `docs/db_design.md`는 구식이며 폐기되었다. 제3의 장소에 또 기술하지 않는다.

### 확장성 원칙 — 개수를 코드·스키마에 박지 않는다

**인원 수·게임 수·모드 수를 고정값으로 쓰지 않는다.** 1:1:1 지원이 막힌 원인이
정확히 이것이었다.

| 금지 | 대신 |
| :--- | :--- |
| `player1_*` / `player2_*` 컬럼 | `game_participants` + `seat_no` (행으로 표현) |
| `player` 값이 `1 또는 2`라는 전제 | `seat_no` 는 1..N |
| `GameStatus.PLAYER1_WIN` / `PLAYER2_WIN` | 승자는 `winner_seat_no`, 참가자별 `result` |
| `goal_row` 단일 축 | 목표를 **축 + 값**으로 (3번 좌석은 열이 목표다) |
| `game`·`mode` 를 DB ENUM 으로 | 문자열 컬럼. 값 추가에 마이그레이션이 불필요하다 |
| 단일 `opponent` 전제 | 상대는 **목록**이다 |

이 원칙은 **DB뿐 아니라 게임 엔진에도 적용된다.** 현재
`app/games/maze/core/` 전반이 2인 전제이며, 일반화 작업 목록은
[`../ROADMAP.md`](../ROADMAP.md) M3에 있다.

> 판단 기준: "인원이 4명이 되면 무엇을 고쳐야 하는가?"를 물었을 때
> **행 추가 외에 스키마·코드 변경이 필요하면 하드코딩이다.**

### `users` — 변경

| 컬럼 | 현재 | 변경 |
| :--- | :--- | :--- |
| `id` | `Integer` PK | 유지 |
| `nickname` | `String(20)` unique **not null** | **nullable로 변경.** 익명 계정은 닉네임이 없다 |
| `password_hash` | `String(128)` not null | **폐기.** 자체 비밀번호 인증을 쓰지 않는다 |
| `session_token` | `String(64)` unique not null | **폐기.** JWT로 대체 |
| `score` | `Float` | **폐기.** 일일 점수판 전용이었다 |
| `wins`, `losses` | `Integer` | **이동.** 게임별 전적 테이블로 분리 (아래 `user_game_stats`) |
| `best_turn_count` | `Integer` nullable | **폐기.** 일일 점수판 전용 |
| `is_online` | `Boolean` | 유지. 단 실시간 접속 상태는 Redis가 권위이고 이 컬럼은 참고값이다 |
| `current_game_id` | `String(36)` nullable | 유지 |
| `last_active_at`, `created_at` | `DateTime` | 유지 |
| **신규** `auth_type` | — | `String` — `anonymous` \| `kakao` |
| **신규** `device_key` | — | `String(36)` unique nullable, index. 익명 계정 식별자 (§1.1) |
| **신규** `kakao_sub` | — | `String` unique nullable, index. 카카오 OIDC `sub` (§1.2) |
| **신규** `merged_at` | — | `DateTime` nullable. 병합 완료 시각 (§2.4) |
| **신규** `merged_from_user_id` | — | `Integer` FK nullable. 병합 원본 익명 계정 |
| **신규** `is_active` | — | `Boolean` default true. 병합된 익명 계정을 비활성 처리 (§2.4) |

### `refresh_tokens` — 신규

리프레시 토큰 회전과 재사용 감지(§1.4)에 필요하다.

| 컬럼 | 타입 | 비고 |
| :--- | :--- | :--- |
| `jti` | `String(36)` PK | 토큰 고유 ID |
| `user_id` | `Integer` FK → `users.id`, index | |
| `issued_at`, `expires_at` | `DateTime` | |
| `revoked_at` | `DateTime` nullable | 폐기 시각 |
| `replaced_by_jti` | `String(36)` nullable | 회전 추적. 폐기된 토큰이 재사용되면 탈취로 판정 |

만료된 행의 정리 방식:

1. 모든 조회에 `revoked_at IS NULL AND expires_at > now()` 조건을 건다
2. **토큰 회전·로그인 시** 같은 `user_id`의 만료 행을 함께 삭제한다
   (`DELETE … WHERE user_id=? AND expires_at < now()`) — 정리 부하가 유저
   트래픽에 비례하고, 유저당 행 수가 활성 기기 수 수준으로 유지된다
3. 인덱스 `(user_id, expires_at)`을 둔다
4. 삭제 기준은 `revoked_at`이 **아니라 `expires_at`**이다 — 폐기된 행이
   만료까지 남아야 `replaced_by_jti` 체인으로 재사용(탈취)을 잡을 수 있다 (§1.4)

**주기 작업을 만들지 않는다.** 이는 [`../ROADMAP.md`](../ROADMAP.md)의
스케줄러 제거 판단 근거 중 하나다.

### `user_game_stats` — 신규

`(game, mode)` 조합별 MMR·전적(§4.2).

| 컬럼 | 타입 | 비고 |
| :--- | :--- | :--- |
| `user_id` | `Integer` FK, **PK 일부** | |
| `game` | `String`, **PK 일부** | `maze_1p`, `gomoku_renju`, … |
| `mode` | `String`, **PK 일부** | `duel`, `trio`, … |
| `mmr` | `Integer` default 1000 | |
| `wins`, `losses` | `Integer` default 0 | |
| `games_played` | `Integer` default 0 | 배치 판정용 |
| `updated_at` | `DateTime` | |

복합 PK `(user_id, game, mode)`. 게임이 늘어도 모드가 늘어도 **행만 늘고
스키마는 그대로다.** `game`·`mode`를 DB 열거형(ENUM)으로 만들지 않는다 —
값을 추가할 때마다 마이그레이션이 필요해진다 (아래 확장성 원칙).

리더보드 조회를 위해 `(game, mode, mmr DESC)` 인덱스가 필요하다.

### `solo_progress` — 신규

계정 병합의 이관 대상(§2.1). 게임별 솔로 진행도.

| 컬럼 | 타입 | 비고 |
| :--- | :--- | :--- |
| `user_id` | `Integer` FK, PK 일부 | |
| `game` | `String`, PK 일부 | |
| `payload` | `JSONB` | 게임별 구조. 서버는 내용을 해석하지 않고 보관한다 |
| `updated_at` | `DateTime` | |

> 서버가 내용을 해석하지 않는 이유: 솔로 데이터는 §3.3 원칙 1에 따라 "가벼운
> 방어"만 적용하며 서버 검증 대상이 아니다. 구조를 서버 스키마로 고정하면
> 게임 규칙이 바뀔 때마다 마이그레이션이 필요해진다.

### `game_sessions` — 변경 (⚠️ 1:1:1 차단 요인)

**현 스키마는 2인 하드코딩이며 1:1:1을 지원할 수 없다.**

| 컬럼 | 현재 | 문제 |
| :--- | :--- | :--- |
| `player1_name`, `player2_name` | `String(50)` | 3번째 플레이어를 담을 곳이 없다 |
| `player1_user_id`, `player2_user_id` | `Integer` FK | 동일 |
| `winner` | `Integer` nullable | 1\|2 전제 |
| `current_turn` | `Integer` default 1 | 1\|2 전제 |

**해결: `game_participants` 테이블로 정규화한다.**

| 컬럼 | 타입 | 비고 |
| :--- | :--- | :--- |
| `game_id` | `String(36)` FK, PK 일부 | |
| `seat_no` | `Integer`, PK 일부 | 1, 2, 3 … |
| `user_id` | `Integer` FK nullable | AI면 `null` |
| `display_name` | `String(50)` | |
| `is_ai` | `Boolean` | |
| `result` | `String` nullable | `win` \| `lose` \| `draw` \| `abandoned` \| `void` |
| `rank` | `Integer` nullable | 순위. 산정 규칙은 [`games/maze.md`](games/maze.md) §9 |
| `elimination_reason` | `String` nullable | `surrender` \| `time_forfeit` \| `disconnect_forfeit` |
| `mmr_before`, `mmr_after` | `Integer` nullable | 랭크전만 |

전부 좌석 행의 열이므로 인원이 늘어도 행만 는다.

`game_sessions`에서 `player*_name`·`player*_user_id`를 제거하고, `winner`는
`winner_seat_no`로 바꾼다. `current_turn`은 `current_seat_no`로 바꾼다.

> 대안으로 `player3_*` 컬럼을 추가하는 방법이 있으나 택하지 않는다 — 인원이
> 늘 때마다 스키마가 바뀌고, 3인 중 2명만 채워진 상태를 표현하기 어렵다.
> 위 확장성 원칙에 정면으로 위배된다.

### `game_moves`, `ActionType`(DB), `game_sessions.game_history` — 폐기 완료

리플레이 기능을 폐기하면서 함께 제거했다. 수 단위 기록을 저장하지 않는다.

| 대상 | 비고 |
| :--- | :--- |
| `game_moves` 테이블 | `game_state_snapshot`(수마다 전체 상태) 포함 |
| DB `ActionType` enum | `app/games/maze/core/game_state.py`의 **엔진 `ActionType`은 유지**된다 (AI가 사용) |
| `game_sessions.game_history` | 구 JSONB 방식. 이미 갱신이 중단된 죽은 컬럼이었다 |
| `GameSession.moves` relationship | |

복원이 필요하면 git에서 꺼낸다 — [`../ROADMAP.md`](../ROADMAP.md) 향후 확장에
복원 지점 커밋이 적혀 있다.

### `daily_champions` — 폐기

랭킹을 MMR 하나로 단순화하면서 일일 리셋 개념을 없앤다. 이 테이블과 이를 쓰는
`RankingRepository`의 챔피언 관련 메서드, 일일 리셋 스케줄러가 함께 폐기 대상이다.

### `match_queue`, `game_rooms` — 권위 경계 정리

현재 **같은 개념이 두 곳에 병존**한다.

| 개념 | DB 테이블 | in-process |
| :--- | :--- | :--- |
| 매치메이킹 큐 | `match_queue` (`models.py:115`) | `app/ws/matchmaking.py:45` `_user_entries` |
| 게임 방 | `game_rooms` (`models.py:150`) | `app/ws/room_manager.py:80` `_rooms` (동명 dataclass는 :37) |

**M3 이후의 권위 경계:**

| 데이터 | 권위 | 이유 |
| :--- | :--- | :--- |
| 실시간 큐·방 상태 | **Redis** | §2.2. 워커 간 공유가 필요하고 수명이 짧다 |
| 종료된 게임 기록 | **PostgreSQL** (`game_sessions`, `game_participants`, `game_moves`) | 영속 기록 |

→ `match_queue`·`game_rooms` **테이블은 폐기한다.** 실시간 상태를 DB에 쓰면
Redis와 이중 기록이 되고 정합성 문제가 생긴다. 방 기록이 필요하면 게임이
시작될 때 `game_sessions`에 남으므로 충분하다.

성사되지 않은 매칭 시도의 통계는 전용 테이블을 만들지 않고 **구조화 로그**로
남긴다. 필드 이름을 지금 고정해 둔다(나중에 집계 테이블로 그대로 옮긴다).

| 필드 | 값 |
| :--- | :--- |
| `event` | `match_found` \| `match_cancelled` \| `queue_left` |
| `game` / `mode` | `maze_1p` / `duel`·`trio`… |
| `wait_ms` | 큐 진입 ~ 이벤트까지 경과 시간 |
| `mmr_gap` | 성사 시 참가자 MMR 최대 차 |
| `queue_size` | 이벤트 시점 큐 길이 |

유일한 비용은 소급 데이터가 로그 보존 기간까지만 복구된다는 것이다. `mode`가
필드이므로 새 모드가 생겨도 값만 늘고 스키마는 그대로다.

---

## §6 폐기 대상과 대체 경로

현존 **25개 라우트 전부**를 다룬다.

> 열거는 AST로 수행했다. `grep '@router.get("...")'` 로는 14개를 놓친다 —
> `app/api/quoridor.py`는 데코레이터가 여러 줄이다.

### `/api/v1/users/*` (6개) — 전면 교체

| 기존 | 대체 |
| :--- | :--- |
| `POST /register` | **폐기.** `POST /api/v1/auth/anonymous` 또는 `/auth/kakao`가 계정을 생성한다 |
| `POST /login` | **폐기.** `POST /api/v1/auth/kakao` |
| `GET /me` | `GET /api/v1/me` (응답 구조 변경 — `data` 봉투) |
| `POST /heartbeat` | **폐기.** 접속 상태는 WebSocket 연결 자체로 판정한다. 별도 하트비트 REST는 불필요하며 레이트 리미트만 소모한다 |
| `POST /logout` | `POST /api/v1/auth/logout` (리프레시 토큰 폐기) |
| `GET /check-nickname/{nickname}` | `GET /api/v1/nicknames/availability?nickname=` (§3) |

### `/api/v1/ranking/*` (4개) — 전면 교체

| 기존 | 대체 |
| :--- | :--- |
| `GET /leaderboard` | `GET /api/v1/leaderboard?game=&mode=` (MMR 기준, 커서 페이지네이션) |
| `GET /my-rank` | `GET /api/v1/me/stats` (`(game, mode)` 별 `rank` 포함) |
| `GET /champion` | **폐기.** 일일 리셋 개념 제거 |
| `GET /champions` | **폐기.** 동일 |

### `/api/v1/quoridor/*` (14개) — 미로 WS 프로토콜로 대체

| 기존 | 대체 |
| :--- | :--- |
| `POST /games` | WS `join_queue` / `create_room` ([`games/maze.md`](games/maze.md)) |
| `GET /games/{id}` | WS `game_state` |
| `DELETE /games/{id}` | WS `surrender` 또는 방 이탈 |
| `POST /games/{id}/move` | WS `move` |
| `POST /games/{id}/wall` | WS `wall` |
| `POST /games/{id}/ai-move` | **폐기.** 솔로 AI는 두 경로로 나뉜다 — **오프라인 솔로**(비로그인)는 Dart Isolate AI로 §1.1의 "100% 오프라인"을 그대로 유지하고, **온라인 AI 좌석**(로그인)은 `game_participants.is_ai = true`로 멀티 프로토콜을 그대로 재사용하며 서버 엔진(`simple_ai.py`)이 둔다(MMR 미반영, 랭크전 아님). 어느 쪽도 이 엔드포인트가 필요 없다. 둘 다 멀티플레이 상호작용 검증 이후 착수한다. `simple_ai.py`는 온라인 AI 좌석의 기반으로 보존하되 Phase 1에서는 미노출이다 |
| `POST /games/{id}/abandon` | WS `surrender` |
| `POST /games/{id}/recover` | WS 재접속 흐름 ([`games/maze.md`](games/maze.md)) |
| `GET /games/{id}/valid-moves` | **폐기.** 서버가 유효 수 목록을 주면 Fog of War가 무너진다 — 시야 밖 정보가 드러난다. 클라이언트가 자신의 시야 내에서 계산한다 |
| `GET /games/{id}/history` | **폐기 완료.** 리플레이 기능 제거 (아래) |
| `GET /games/{id}/replay/moves` | **폐기 완료.** 리플레이 기능 제거 (아래) |
| `GET /games/{id}/replay/state/{step_no}` | **폐기 완료.** 리플레이 기능 제거 (아래) |
| `GET /games/{id}/replay/total` | **폐기 완료.** 리플레이 기능 제거 (아래) |
| `GET /sessions` | **폐기.** 진행 중 세션 목록은 접속 시 WS가 통보한다 |

**리플레이·히스토리 5개 — 폐기 완료**

`PLATFORM_ARCHITECTURE.md`에 리플레이 요구가 없고, 구현을 새 구조로 이관하는
비용과 노이즈가 이득보다 컸다. 다음을 모두 제거했다.

| 대상 | 내용 |
| :--- | :--- |
| 엔드포인트 5개 | 리플레이 4 + `history` 1 |
| `game_moves` 테이블 | `game_state_snapshot` 포함 |
| DB `ActionType` enum | 엔진 `ActionType`은 유지 (AI 사용) |
| `game_sessions.game_history` | 이미 갱신 중단된 죽은 컬럼 |
| `GameSerializer`의 리플레이 부분 | `MoveRecord`, `ReplayData`, `replay_to_json`/`from_json`, `apply_move_to_state`, `reconstruct_state_at_step` — 외부 참조 0건이었다 |
| repository 메서드 7개 / service 메서드 3개 | |
| 테스트 11개 | `test_replay.py` 전체 + `TestGameMoves` 클래스 |

`history`가 함께 폐기된 이유: 같은 `game_moves` 테이블에 의존하므로 테이블만
남기면 노이즈 방지 목적이 무산된다.

**다시 필요해지면 git에서 복원한다.** 복원 지점 커밋은
[`../ROADMAP.md`](../ROADMAP.md) 향후 확장에 한 줄로 기록되어 있다. 그때
Fog of War 정책(전체 공개 vs 플레이어 시점 재생)과 함께 재설계한다.

### `WEBSOCKET /ws/game` (1개) — 재설계

구 Quoridor 2P 프로토콜이다. 1인칭 미로 프로토콜로 재설계한다
([`games/maze.md`](games/maze.md)). 기존 `WSMessageType` 25종 어휘는 재사용한다.

현재 이 라우터는 `app/main.py`에 **등록되어 있지 않다** — 동작하는 기능으로
오인되지 않게 한 의도적 조치다. 판정 내역은 `server/app/ws/__init__.py` docstring.

---

## 미결 사항 요약

**현재 미결 없음.**

### 확정된 항목 (초판에서 미결이었던 것)

| 항목 | 결정 |
| :--- | :--- |
| 리플레이·히스토리 | **폐기.** 코드·DB·테스트 제거 완료. git 복원 지점만 기록 (§6) |
| MMR 분리 단위 | **`(game, mode)` 조합.** 게임별 분리 방식을 모드에도 적용 (§4.2) |
| 솔로 AI | **두 경로로 분리.** 오프라인 솔로는 Dart Isolate, 온라인 AI 좌석은 서버 엔진(`simple_ai.py`). 둘 다 멀티 검증 이후, `ai-move`는 폐기 (§6) |
| 유저 선택 병합 | **솔로 플레이 도입 시점으로 유보.** 거절 시 클라이언트는 로컬 진행도를 삭제하지 않는다 (§2.3) |
| `refresh_tokens` 정리 | **토큰 회전·로그인 시** 만료 행 삭제. 기준은 `expires_at`. 주기 작업 없음 (§5) |
| 매칭 시도 통계 | **전용 테이블 없이 구조화 로그.** 필드 고정(`event`/`game`/`mode`/`wait_ms`/`mmr_gap`/`queue_size`) (§5) |

### 운영 중 조정 항목

설계는 확정됐고 서버 설정값의 숫자만 운영 데이터로 조정한다. 하드코딩 금지
원칙(§5 확장성 원칙)의 실천이다.

| 항목 | 초기값 | 조정 신호 | 위치 |
| :--- | :--- | :--- | :--- |
| MMR K 계수 | duel 40/24, trio 32/16 | 레이팅 수렴 속도 | §4.2 |
