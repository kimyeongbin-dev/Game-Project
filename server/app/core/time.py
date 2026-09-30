"""시간 유틸 — 프로젝트 표준 UTC 시각."""

from datetime import datetime, timezone


def utcnow() -> datetime:
    """timezone-naive UTC 현재 시각.

    datetime.utcnow() 는 Python 3.12+ 에서 deprecated 이며 제거 예정이다.
    다만 DB의 DateTime 컬럼과 to_dict() 의 isoformat() + "Z" 직렬화가
    naive UTC 를 전제하므로, tzinfo 를 떼어내 기존 동작을 그대로 유지한다.

    NOTE: app/db/models.py, app/games/maze/core/game_state.py,
          app/services/quoridor_service.py 에 동일한 로컬 헬퍼가 각각 정의되어
          있다. 이 모듈로 일원화하는 정리는 별도로 진행한다.
    """
    return datetime.now(timezone.utc).replace(tzinfo=None)
