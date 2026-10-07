# 플랫폼 공통 API 설계서

> **대응 명세:** [`PLATFORM_ARCHITECTURE.md`](../../PLATFORM_ARCHITECTURE.md) §1.1 (하이브리드 플레이),
> §3.2 (하드웨어 금고), §3.3 (데이터 신뢰 분리)
>
> **범위:** 인증, 계정 병합, 프로필, 전적·MMR. 게임별 API는 [`games/`](games/)에 있다.
>
> **상태:** 설계 확정 (2026-10-01). 구현 순서는 [`../ROADMAP.md`](../ROADMAP.md)를 따른다.
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
>
> **리밋 키 = 실제 클라이언트 IP (M4-1).** 앞단 Caddy 가 신뢰한 엣지(`CADDY_TRUSTED_PROXIES`)의 `X-Forwarded-For` 로 클라이언트를
> 판정해 그 주소 **하나**로 다시 쓰고, 서버(uvicorn)는 Caddy 주소(`FORWARDED_ALLOW_IPS`)에서 온 값만 믿는다. 엣지는 받은 XFF
> 뒤에 접속 주소를 덧붙이므로("위조, 실제") Caddy 는 **strict**(`trusted_proxies_strict`)로 오른쪽부터 읽는다 — 클라이언트가
> 보낸 값은 키가 되지 않는다. 엣지 대역이 빠지면 모든 사용자가 엣지 주소 하나를 공유하므로 운영 오버레이는 이 값을 필수로 받는다.
> 다중 워커·프록시 경유·다중 홉 정확도는 하네스 P1 이 잰다
> (`docs/research/2026-10-07-M4-1-프록시-실측.md`).
>
> **CORS (M4-1):** 허용 오리진은 `CORS_ALLOWED_ORIGINS`(JSON 목록). 비우면 개발 `*`, **운영은 없음**(브라우저 오리진 불허 —
> 네이티브 앱은 Origin 을 보내지 않는다). 운영에 `*` 를 넣으면 서버가 기동하지 않는다. 인증이 bearer 라 credentials 는 허용하지
> 않는다. WS 핸드셰이크도 같은 목록으로 거른다(`games/maze.md` §2).

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
그렇지 않으면 **모든 사용자가 하나의 제한을 공유**한다. 신뢰 경계는 위 "리밋 키" 문단(M4-1) —
서버는 `--forwarded-allow-ips *` 를 쓰지 않는다(직접 닿는 누구든 IP 를 위조한다, `scripts/check-proxy-config.sh`).

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

### `game_sessions` — 변경 완료 (M3 2단계, 커밋 `c26f4ad`)

구 스키마는 2인 하드코딩(`player1_*`/`player2_*`, `winner`·`current_turn` 이 1\|2 전제)이라
1:1:1을 지원할 수 없었다. **`game_participants` 로 정규화**하고, `game_sessions` 는
**게임 한 판의 시작·종료 기록**만 담는다.

| 컬럼 | 타입 | 비고 |
| :--- | :--- | :--- |
| `game_id` | `String(36)` PK | |
| `game` | `String(32)` | `maze_1p`, … |
| `mode` | `String(16)` | `duel`, `trio`, … |
| `is_ranked` | `Boolean` | |
| `status` | `String(16)`, index | `in_progress` \| `finished` \| `void` |
| `end_reason` | `String(16)` nullable | `goal_reached` \| `last_standing` \| `server_fault` ([`games/maze.md`](games/maze.md) §10) |
| `winner_seat_no` | `Integer` nullable | |
| `turn_count` | `Integer` | 종료 시 기록 |
| `started_at` / `ended_at` | `DateTime` / nullable | |

**진행 중 상태를 DB 에 두지 않는다.** 초판은 `current_turn` 을 `current_seat_no` 로
이름만 바꾸라고 적었으나, 이는 게임 상태의 권위를 정하기 **전**의 문장이다. M3 0단계
실측으로 진행 중 상태의 권위는 Redis `game:<id>:state` 로 정해졌다([`games/maze.md`](games/maze.md) §8).
차례·위치·벽을 DB 에도 쓰면 행동마다 두 곳을 맞춰야 하는 이중 기록이 된다. 그래서
`current_turn`·`game_state`(JSONB)를 이름 변경 없이 **삭제**했다. 같은 이유로
`ai_difficulty`(온라인 AI 좌석 착수 시 좌석 단위로 재설계)와 `is_deleted`(폐기된 REST
`DELETE` 전용)도 삭제했다.

DB 의 역할은 둘이다. ① **시작 시** `status = in_progress` 로 행을 만든다 — §8 fail-safe 가
"Redis 상태가 사라진 진행 중 게임"을 찾는 기준이다. ② **종료 시** 결과를 채운다.
`game`·`mode`·`status`·`end_reason` 은 DB ENUM 이 아닌 문자열이며, 허용 값은
`app/db/repository.py` 가 검증한다(위 확장성 원칙).

**`game_participants`** — 좌석 하나가 행 하나다.

| 컬럼 | 타입 | 비고 |
| :--- | :--- | :--- |
| `game_id` | `String(36)` FK(`ON DELETE CASCADE`), PK 일부 | |
| `seat_no` | `Integer`, PK 일부 | 1, 2, 3 … (1..N 연속) |
| `user_id` | `Integer` FK nullable | AI면 `null` |
| `display_name` | `String(50)` | |
| `is_ai` | `Boolean` | |
| `result` | `String` nullable | `win` \| `lose` \| `draw` \| `abandoned` \| `void` |
| `rank` | `Integer` nullable | 순위. 산정 규칙은 [`games/maze.md`](games/maze.md) §9 |
| `elimination_reason` | `String` nullable | `surrender` \| `time_forfeit` \| `disconnect_forfeit` |
| `mmr_before`, `mmr_after` | `Integer` nullable | 랭크전만 |

전부 좌석 행의 열이므로 인원이 늘어도 행만 는다. 리포지토리 테스트가 2·3·4좌석으로
파라미터화되어 이를 고정한다(`tests/db/test_game_session_repository.py`).

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

### `daily_champions` — 폐기 완료 (M3 2단계, 커밋 `3e889a9`)

랭킹을 MMR 하나로 단순화하면서 일일 리셋 개념을 없앤다. 이 테이블과 이를 쓰는
`RankingRepository`의 챔피언 관련 메서드, 일일 리셋 스케줄러가 함께 폐기 대상이다.

### `match_queue`, `game_rooms` — 권위 경계 정리

M3 2단계 전에는 **같은 개념이 두 곳에 병존**했다. 둘 다 정리했다 — 테이블은 2단계에서 폐기,
in-process 상태는 3단계에서 Redis 로 옮겼다(아래 "Redis 키 스키마").

| 개념 | DB 테이블 (폐기) | in-process (폐기) | 현재 |
| :--- | :--- | :--- | :--- |
| 매치메이킹 큐 | `match_queue` | `app/ws/matchmaking.py` `_user_entries` | Redis `queue:{game}:{mode}` |
| 게임 방 | `game_rooms` | `app/ws/room_manager.py` `_rooms` | Redis `room:{code}` |

**M3 이후의 권위 경계:**

| 데이터 | 권위 | 이유 |
| :--- | :--- | :--- |
| 실시간 큐·방 상태 | **Redis** | §2.2. 워커 간 공유가 필요하고 수명이 짧다 |
| 종료된 게임 기록 | **PostgreSQL** (`game_sessions`, `game_participants`) | 영속 기록 |

→ `match_queue`·`game_rooms` **테이블은 폐기했다**(M3 2단계, 커밋 `c26f4ad`). 실시간 상태를 DB에 쓰면
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

### Redis 키 스키마 — 확정 (M3 3단계)

실시간 상태의 권위인 Redis 키다(논리 DB 0). 키 문자열은 `server/app/db/redis_keys.py`
한 곳에서만 만든다. `{game}` = 게임 식별자(`maze_1p`), `{mode}` = 배치 테이블 키.
**인원 수가 들어가는 키는 없다** — 4인 모드는 배치 테이블에 행을 추가하는 것으로 끝난다.

| 키 | 타입 | 값 | TTL | 쓰는 쪽 | 읽는 쪽 |
| :--- | :--- | :--- | :--- | :--- | :--- |
| `game:{id}:state` | STRING | `GameState.to_dict()` JSON (`schema_version` 포함) | 진행 중 없음 / 종료 후 `game_finished_ttl_sec`(300) | 게임 서비스 — 락 안에서, 락 토큰 펜싱 | 게임 서비스, 재접속 |
| `game:{id}:meta` | STRING | `{game, mode, is_ranked, room_code, created_at, players:[{seat_no, user_id, nickname, is_ai}]}` — 불변 | state 와 같다 | 게임 서비스(생성 시 1회) | 게임 서비스(유저 → 좌석), WS 핸들러 |
| `game:{id}:lock` | STRING | 무작위 토큰 | `PX game_lock_ttl_ms`(5000) | 락 헬퍼 | 락 헬퍼, 펜싱 쓰기 |
| `queue:{game}:{mode}` | ZSET | member=`user_id`, score=입장 시각(epoch ms) | 없음 | 매치메이킹 | 매치메이킹 |
| `queue:{game}:{mode}:entries` | HASH | `user_id` → `{nickname, mmr}` | 없음 | 매치메이킹 | 매칭 Lua |
| `match:{id}` | STRING | `{game, mode, ready_deadline_ms, players:[{seat_no, user_id, nickname, mmr, joined_at_ms, ready}]}` | `match_record_ttl_sec`(60) — 안전망 | 매치메이킹 | 매치메이킹 |
| `match:{id}:lock` | STRING | 토큰 | PX | 락 헬퍼 | 락 헬퍼 |
| `room:{code}` | STRING | `{code, game, mode, capacity, status, game_id, created_at, players:[{seat_no, user_id, nickname, is_host, is_ready}]}` | `room_ttl_sec`(3600), 변경마다 갱신 | 방 서비스 | 방 서비스 |
| `room:{code}:lock` | STRING | 토큰 | PX | 락 헬퍼 | 락 헬퍼 |
| `user:{uid}:activity` | STRING | `queue:{game}:{mode}` \| `match:{id}` \| `room:{code}` \| `game:{id}` | 담는 대상과 같게(게임은 없음) | 전 서비스 — 진입 `SET NX`, 전이·해제 CAS | 전 서비스, 재접속 |
| `{ns}:game:{id}:events` | Pub/Sub 채널 | 이벤트 JSON `{kind, scope, scope_id, recipients, hint, seq}` — 권위 없음 | — | 게임 서비스(상태를 쓴 직후, 락 안) | 워커별 구독 버스 |
| `{ns}:match:{id}:events` | Pub/Sub 채널 | 〃 | — | 매치메이킹 | 〃 |
| `{ns}:room:{code}:events` | Pub/Sub 채널 | 〃 | — | 방 서비스 | 〃 |
| `{ns}:user:{uid}:events` | Pub/Sub 채널 | 연결 제어 `session_replaced {conn_id}` — 메시지가 아니다(M3 7단계) | — | WS 핸들러 | 〃 (그 유저의 옛 연결을 4000 으로 닫는다) |
| `game:{id}:vision:{seat_no}` | STRING | 좌석의 누적 관측 `{v, edges:[[row, col, "h"\|"v", wall]…], last_seen:[{seat_no, row, col, turn}…]}` ([`games/maze.md`](games/maze.md) §6) | state 와 같다 | 게임 서비스 — 생성 시 MULTI, 수락된 행동마다 **state 와 같은 펜싱 쓰기 한 번**(M3 5단계) | 좌석별 화면(자기 좌석 키만), 탈락자 관전 패킷 |
| `game:{id}:clocks` | STRING | `{v, turn_started_at_ms, stopped_at_ms, started_at_ms, seats:[{seat_no, remaining_ms, conn_remaining_ms, disconnected_at_ms, grace:[[from, until]…], frozen}]}` — 마지막 정산 시점의 두 시계 ([`games/maze.md`](games/maze.md) §8) | state 와 같다 | 게임 서비스 — 생성 시 MULTI, 이후 **state 와 같은 펜싱 쓰기 한 번**(M3 6단계) | 게임 서비스, 좌석별 화면(공개 잔량) |
| `deadlines:{game}` | ZSET | member=`clock:<game_id>` \| `grace:<game_id>:<seat_no>` \| `ready:<match_id>`, score=소진 예정 시각(epoch ms, Redis TIME) | 없음 | 게임 서비스(펜싱 쓰기 Lua 안), 매치메이킹(매치 기록과 MULTI), 스위퍼(리스 클레임) | 스위퍼 |
| `deadlines:{game}:scan` | STRING | 토큰 — 상태 유실 점검을 주기마다 한 워커만 | `PX lost_scan_interval_sec` | 스위퍼 | 스위퍼 |
| `game:{id}:result` | STRING | 종료 결과 `{end_reason, winner_seat_no, turn_count, results}` — DB 기록에 실패했을 때만 | 없음(기록 재시도 성공 시 삭제) | 게임 서비스(종료 처리) | 스위퍼 유실 점검(무효 대신 재시도) |
| `store:alive` | STRING | 전역 하트비트 — 어느 워커든 Redis 에 마지막으로 성공한 시각(epoch ms). 이후 공백 = 장애 | 없음 | 스위퍼 전용 하트비트 루프(200 ms, 전용 연결)·스위퍼 회차·게임 서비스의 복구 뒤 첫 성공 처리 — 모두 같은 하트비트 Lua(공백이면 `store:outages` 에 함께 기록, 시각을 되감지 않음) | 시계 정산(잠정 면제) |
| `store:workers` | ZSET | member=워커 id(`app/core/worker.py`), score=그 워커의 마지막 하트비트 | 없음(다 처리한 죽은 워커는 제거) | 스위퍼(자기 하트비트, 죽은 워커 리스 클레임) | 스위퍼 |
| `store:workers:{wid}:seats` | ZSET | member=`<game_id>:<seat_no>` — 그 워커가 연결을 가진 좌석 | 없음 | 게임 서비스 — **시계와 같은 펜싱 쓰기**(소유가 바뀐 만큼 이동) | 스위퍼(죽은 워커의 좌석을 끊김으로) |
| `game:{id}:version` | STRING | 게임 이벤트 번호(정수) — 커밋되는 이벤트마다 +1, 와이어 `version`([`games/maze.md`](games/maze.md) §1) | state 와 같다 | 게임 서비스 — **state 와 같은 펜싱 쓰기**(M3 7단계, 검토 L23) | 게임 서비스, 좌석별 화면(재동기화 번호) |
| `user:{uid}:conn` | STRING | 그 유저의 현재 WS 연결 id `<worker_id>:<토큰>` — 클러스터에 연결 하나 | `EX 86400`(큐 티커가 로컬 연결의 TTL 갱신) | WS 핸들러(접속 시 `GET` 뒤 `SET` — 재시도에 이전 값을 잃지 않게. 연결이 끝나면 자기 값일 때만 삭제) | WS 핸들러(이전 연결이 다른 워커면 `session_replaced` 발행), 버스(교체·재구독 확인), 게임 서비스(**락 안** — 좌석 소유는 그 유저의 현재 연결만 기록, 다른 살아 있는 연결이 현재면 끊김 무시) |
| `ws:{ns}:connect:{uid}` | STRING | 분당 WS 접속 수 — **리미터 논리 DB**(앱 상태 DB 가 아니다) | `EX 60`(첫 INCR 때) | WS 핸들러(INCR) | WS 핸들러(`ws_connect_per_minute` 초과면 1013) |
| `ws:{ns}:connect-ip:{ip}` | STRING | 클라이언트 IP(IPv6 는 `/64`) 별 분당 WS **접속 실패** 수(무효 토큰·허용 안 된 Origin) — 리미터 논리 DB. IP 는 프록시가 판정한 값(M4-1) | `EX 60`(첫 INCR 때) | WS 핸들러(실패 때만 INCR — 유효 토큰은 세지 않는다) | WS 핸들러(`ws_connect_per_minute_ip` 초과면 1013·로그 없음) |
| `store:outages` | ZSET | member=`"<start_ms>-<end_ms>"`, score=end_ms — 전역 하트비트 공백으로 관측한 Redis 장애 구간 | 원소별 `outage_retention_sec`(86400) 뒤 정리 | `store:alive` 와 같은 하트비트 Lua(쓰는 쪽도 같다) | 시계 정산(면제 구간), 스위퍼(긴 장애 무효 훑기·사망 판정 유예) |

**설계 근거**

- **state 와 meta 를 나눈다.** 엔진은 유저를 모른다. meta 는 생성 후 바뀌지 않으므로 락 없이 읽어도 된다
- **거절도 저장한다.** 벽 거절은 `wall_rejections` 를 바꾼다([`games/maze.md`](games/maze.md) §7)
- **펜싱 쓰기.** state 는 "락 토큰이 아직 내 것일 때만 SET" 하는 Lua 로 쓴다. 락 TTL 을 넘긴 행동이
  다음 행동의 결과를 덮어쓰지 못한다
- **시계와 데드라인도 state 와 한 번에 쓴다 (M3 6단계).** `fenced_write` 가 문자열(state·vision·clocks)과 `deadlines:{game}` 의
  `ZADD`/`ZREM` 을 Lua 한 번으로 — 나눠 쓰면 "턴은 바뀌었는데 데드라인이 없다"가 남아 그 게임이 영원히 만료되지 않는다.
  데드라인 점수는 **힌트**다: 스위퍼는 빌려 간(리스) 뒤 게임 락 안에서 저장된 시계로 다시 계산하고, 시각은 워커 벽시계가 아니라
  Redis `TIME` 이다. 키 이름은 예약했던 `{game}:deadlines` 대신 `deadlines:{game}` — 다른 키와 같은 "종류:식별자" 형태이고 테스트 정리 접두어에 들어간다
- **시야는 state 와 한 번에 쓴다 (M3 5단계).** 수락된 행동마다 좌석 전원을 다시 관측하고(남의 이동이 내 시야를
  바꾼다) state + 좌석별 vision 을 Lua 한 번(`fenced_mset`)으로 같은 EX 와 함께 쓴다 — 전부 또는 전무. 나눠 쓰면 그 사이
  장애로 state 는 다음 턴인데 발견 맵은 이전 턴이 되고, 그 턴의 목격이 영구히 사라진다. 탈락 좌석은 탈락 직전 관측으로
  동결되지만 종료 TTL 은 함께 받는다. **좌석별 키**로 나눈 것은 플레이어 화면이 자기 좌석 키만 읽게 하기 위해서다
- **활동 키 하나로 배타성을 보장한다.** "동시에 하나의 큐에만"과 큐·방 동시 참가 금지가 `SET NX` 하나로
  원자적으로 성립한다. 같은 키가 재접속 시 진행 중 게임을 찾는 색인이다. 다른 활동 중이면 그 종류에 맞는
  §13 코드(`already_in_queue`·`already_in_room`·`already_in_game`)로 거절한다
- **매칭은 Lua 한 번이다.** 정원(`seats`)이 찼을 때만 `ZPOPMIN seats` 를 한다. 정원은 게임 서비스가
  배치 테이블에서 넘긴다. Phase 1 은 FIFO 라 주기 루프 없이 입장할 때마다 시도한다
- **좌석:** 랭크 매칭은 seat_no 를 무작위로 섞는다(먼저 들어왔다고 선수를 가져가지 않는다). 친구 방은
  방 seat_no(호스트 = 1, 입장 순)가 그대로 게임 seat_no 다
- **시작 시 DB 를 먼저 쓴다.** `game_sessions` 에 진행 중 행을 만든 뒤 Redis 에 상태를 쓴다. §8 fail-safe 는
  "DB 에는 진행 중인데 Redis 상태가 없다"를 유실 판정 기준으로 쓴다. Redis 쓰기가 실패하면 그 행을 `void` 한다
- **테스트는 논리 DB 1** 을 쓰고, 상태 접두어만 지운다. 같은 DB 의 리미터 카운터를 건드리지 않으려고 `FLUSHDB` 를 쓰지 않는다

**이벤트 채널 — 확정 (M3 4단계)**

- **채널에는 권위가 없다.** Pub/Sub 은 at-most-once 다([실측](../research/2026-10-01-워커-redis-실측.md) E5).
  이벤트는 "바뀌었다"는 통지일 뿐이고, 게임 상태는 받은 워커가 Redis 에서 다시 읽어 **좌석별로** 만든다
  ([`games/maze.md`](games/maze.md) §6). 채널은 모든 워커에 가므로 `hint` 에는 공개 정보만 싣는다 — 좌표·벽·상태는 없다
- **수신자는 발행자가 정한다.** 발행자는 방금 락 안에서 Redis 를 읽었다(meta.players / room.players / match.players).
  받는 워커는 그 목록과 자기 연결 맵의 교집합에만 보낸다. 받는 쪽이 다시 읽으면 그 사이 바뀔 수 있고(해산된 방은 키가 없다)
  이벤트마다 워커 수만큼 조회가 는다
- **워커당 패턴 구독 하나.** 게임·방마다 SUBSCRIBE 하면 유저가 붙은 직후 구독이 끝나기 전의 메시지를 잃고, 채널별
  참조 카운트(프로세스 내 소속 맵)가 다시 생긴다. 턴제라 이벤트가 적어 모든 워커가 전부 받아도 싸다. 채널을 게임·방
  단위로 나눠 둔 것은 팬아웃이 커지면 구독 쪽만 동적 구독으로 바꿀 수 있게 하기 위해서다
- **`{ns}:` 네임스페이스 — 명시 설정.** Pub/Sub 채널은 논리 DB 와 무관하게 **서버 전역**이다. 논리 DB 를 나눠도
  같은 Redis 를 쓰는 테스트의 이벤트가 앱 워커로 간다. 그래서 `PUBSUB_NAMESPACE`(앱 `app`, 테스트 `test`)를 접두어로
  붙인다. DB 번호에서 파생하지 않는다 — 격리가 "테스트는 DB 1" 이라는 다른 약속에 기대면 그 약속이 바뀔 때 조용히
  깨진다. 테스트 픽스처는 `test` 가 아니면 중단하고, production 은 `test` 로 기동하지 않는다
- **방송은 §12 이름으로 바꿔 보낸다(M3 7단계).** 이벤트 kind 는 서비스 어휘이고, 수신자별 와이어 메시지는 `app/ws/delivery.py`
  한 곳이 만든다 — 대응 표는 [`games/maze.md`](games/maze.md) §12 "내부 이벤트 → 와이어". 게임 이벤트의 `seq` 는 게임별
  이벤트 번호(`game:{id}:version`)이고, 수락된 이벤트만 같은 쓰기에서 번호를 받는다
- **끊기면 재구독 → 재동기화.** 버스는 지수 백오프로 새 연결에 다시 구독하고, 직후 자기 소켓 전원에게 각자의
  활동(`user:{uid}:activity`)에 맞는 현재 상태를 보낸다. 유실된 이벤트는 이것으로 메워진다

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
| `GET /champion` | **폐기 완료**(커밋 `3e889a9`). 일일 리셋 개념 제거 |
| `GET /champions` | **폐기 완료**(커밋 `3e889a9`). 동일 |

### `/api/v1/quoridor/*` (14개) — 미로 WS 프로토콜로 대체

> **REST 9개 폐기 완료 (M3 1단계, 커밋 `c36c4f9`).** `app/api/quoridor.py`·`app/schemas/quoridor.py`
> 와 테스트를 삭제했다. 리플레이·히스토리 5개는 그 전에 폐기 완료(아래).

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
([`games/maze.md`](games/maze.md)). 기존 `WSMessageType` 25종 어휘는 재사용한다(정의 파일 `app/schemas/ws_messages.py` 는
M3 3단계에서 `ws_game` 과 함께 삭제했고 7단계에서 같은 어휘로 다시 정의했다).

구 핸들러 `app/ws/ws_game.py` 는 M3 3단계에서 **삭제했다**. maze WS 핸들러는 M3 7단계에서
3단계 서비스(`app/services/maze_game.py`·`matchmaking.py`·`rooms.py`)를 대상으로 새로 작성해
`app/main.py` 에 등록했다 — `WEBSOCKET /api/v1/ws/maze`(`app/ws/maze_handler.py`, 어휘는 `app/schemas/ws_messages.py`).

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
