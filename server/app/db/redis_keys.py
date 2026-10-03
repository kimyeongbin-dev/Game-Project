"""
Redis 키 스키마 — 멀티플레이 상태 키의 단일 출처.

키 문자열을 코드 곳곳에서 조립하지 않는다. 형태·타입·TTL·읽고 쓰는 쪽은
docs/api/platform.md "Redis 키 스키마" 표가 정본이다.

인원 수가 들어가는 키는 없다. `game` 은 게임 식별자(`maze_1p`), `mode` 는 배치
테이블 키(`duel`/`trio`/…)다 — 모드가 늘어도 이 파일은 바뀌지 않는다.

Pub/Sub 채널(4단계)도 여기서 만든다. 키가 아니라 채널이다 — 아래 "이벤트 채널" 절.

시간 체계(6단계): `game:{id}:clocks`(좌석별 두 시계), `deadlines:{game}`(만료 색인 ZSET — member 는
`clock:`·`grace:`·`ready:`), `store:outages`(기록된 Redis 장애 구간).
"""

from app.core.config import settings

# 테스트 픽스처가 정리할 접두어. 리미터 키(같은 테스트 DB)는 여기 없다
PREFIXES = ("game:", "queue:", "match:", "room:", "user:", "deadlines:", "store:")


# ----- 게임 -----

def game_state(game_id: str) -> str:
    """STRING — GameState.to_dict() JSON. 권위 있는 진행 상태"""
    return f"game:{game_id}:state"


def game_meta(game_id: str) -> str:
    """STRING — 생성 후 불변인 메타(모드·랭크 여부·좌석별 유저)"""
    return f"game:{game_id}:meta"


def game_lock(game_id: str) -> str:
    """STRING — 게임별 락 토큰"""
    return f"game:{game_id}:lock"


def game_vision(game_id: str, seat_no: int) -> str:
    """STRING — 좌석의 누적 관측 SeatMemory.to_dict() JSON (발견 맵·마지막 목격, maze.md §6)"""
    return f"game:{game_id}:vision:{seat_no}"


def game_clocks(game_id: str) -> str:
    """STRING — GameClocks.to_dict() JSON (게임 시계·접속 시계, maze.md §8)"""
    return f"game:{game_id}:clocks"


# ----- 데드라인 (시간 체계) -----
# 게임 시계·접속 시계·매치 ready 기한을 하나의 ZSET 에 담고 워커마다 스위퍼가 훑는다(maze.md §8).
# score 는 소진 예정 시각(epoch ms, Redis TIME 기준)이고 **힌트일 뿐이다** — 처리는 락 안에서 다시 계산한다.

DEADLINE_CLOCK = "clock"
DEADLINE_GRACE = "grace"
DEADLINE_READY = "ready"


def deadlines(game: str) -> str:
    """ZSET — member = 아래 deadline_* , score = 소진 예정 시각(epoch ms)"""
    return f"deadlines:{game}"


def deadlines_scan_lock(game: str) -> str:
    """STRING — 상태 유실 점검을 한 워커만 하도록 잡는 락"""
    return f"deadlines:{game}:scan"


def deadline_clock(game_id: str) -> str:
    """현재 차례 좌석의 게임 시계 — 게임당 하나"""
    return f"{DEADLINE_CLOCK}:{game_id}"


def deadline_grace(game_id: str, seat_no: int) -> str:
    """끊긴 생존 좌석의 접속 시계"""
    return f"{DEADLINE_GRACE}:{game_id}:{seat_no}"


def deadline_ready(match_id: str) -> str:
    """매치 ready 응답 기한"""
    return f"{DEADLINE_READY}:{match_id}"


def parse_deadline(member: str) -> tuple[str, str]:
    """member → (종류, 대상 id). grace 는 좌석을 버리고 게임 id 만 — 게임 단위로 한 번에 정산한다"""
    kind, _, rest = member.partition(":")
    return kind, rest.split(":", 1)[0]


def store_outages() -> str:
    """ZSET — member = "<시작ms>-<끝ms>", score = 끝ms. 워커가 관측한 Redis 장애 구간 (시계 면제)"""
    return "store:outages"


# ----- 매치메이킹 -----

def queue(game: str, mode: str) -> str:
    """ZSET — member=user_id, score=입장 시각(epoch ms)"""
    return f"queue:{game}:{mode}"


def queue_entries(game: str, mode: str) -> str:
    """HASH — field=user_id, value=대기 항목 JSON"""
    return f"queue:{game}:{mode}:entries"


def match(match_id: str) -> str:
    """STRING — 성사 후 ready 대기 중인 매치 JSON"""
    return f"match:{match_id}"


def match_lock(match_id: str) -> str:
    return f"match:{match_id}:lock"


# ----- 방 -----

def room(code: str) -> str:
    """STRING — 친구 대전 방 JSON"""
    return f"room:{code}"


def room_lock(code: str) -> str:
    return f"room:{code}:lock"


# ----- 유저 -----

def user_activity(user_id: int) -> str:
    """STRING — 유저의 현재 활동 하나 (아래 activity_* 값)"""
    return f"user:{user_id}:activity"


# ----- user_activity 의 값 -----
# 유저는 동시에 하나의 활동에만 속한다 (maze.md §3). 값 자체가 대상 키를 가리킨다

def activity_queue(game: str, mode: str) -> str:
    return f"queue:{game}:{mode}"


def activity_match(match_id: str) -> str:
    return f"match:{match_id}"


def activity_room(code: str) -> str:
    return f"room:{code}"


def activity_game(game_id: str) -> str:
    return f"game:{game_id}"


def parse_activity(value: str) -> tuple[str, str]:
    """activity 값 → (종류, 나머지). 예: "game:abc" → ("game", "abc")"""
    kind, _, rest = value.partition(":")
    return kind, rest


# ----- 이벤트 채널 (Pub/Sub) -----
# 채널은 논리 DB 와 무관하게 Redis 서버 전역이다. 같은 Redis 를 쓰는 테스트와 앱이
# 섞이지 않도록 명시 설정 `pubsub_namespace`(앱 "app" / 테스트 "test")를 붙인다.
# 워커는 패턴 하나로 전부 구독한다(app/ws/bus.py) — 게임·방 단위로 나눠 두는 것은
# 나중에 구독 쪽만 동적 SUBSCRIBE 로 바꿀 수 있게 하기 위해서다.

EVENT_SCOPES = ("game", "match", "room")


def channel_namespace() -> str:
    return f"{settings.pubsub_namespace}:"


def events(scope: str, scope_id: str) -> str:
    """scope 의 이벤트 채널. scope ∈ EVENT_SCOPES"""
    if scope not in EVENT_SCOPES:
        raise ValueError(f"Unknown event scope: {scope}")
    return f"{channel_namespace()}{scope}:{scope_id}:events"


def game_events(game_id: str) -> str:
    return events("game", game_id)


def match_events(match_id: str) -> str:
    return events("match", match_id)


def room_events(code: str) -> str:
    return events("room", code)


def event_patterns() -> tuple[str, ...]:
    """PSUBSCRIBE 패턴 — 이 네임스페이스의 모든 이벤트 채널"""
    return tuple(f"{channel_namespace()}{scope}:*:events" for scope in EVENT_SCOPES)
