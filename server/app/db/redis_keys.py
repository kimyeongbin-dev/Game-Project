"""
Redis 키 스키마 — 멀티플레이 상태 키의 단일 출처.

키 문자열을 코드 곳곳에서 조립하지 않는다. 형태·타입·TTL·읽고 쓰는 쪽은
docs/api/platform.md "Redis 키 스키마" 표가 정본이다.

인원 수가 들어가는 키는 없다. `game` 은 게임 식별자(`maze_1p`), `mode` 는 배치
테이블 키(`duel`/`trio`/…)다 — 모드가 늘어도 이 파일은 바뀌지 않는다.

예약(아직 만들지 않음): `game:{id}:events`(4단계 Pub/Sub), `game:{id}:vision:{seat_no}`
(5단계 시야), `game:{id}:clocks`·`{game}:deadlines`(6단계 시간 체계).
"""

# 테스트 픽스처가 정리할 접두어. 리미터 키(같은 테스트 DB)는 여기 없다
PREFIXES = ("game:", "queue:", "match:", "room:", "user:")


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
