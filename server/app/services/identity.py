"""
신원 조회 — 인증된 user_id → 상대에게 보일 이름과 MMR (maze.md §2 `connected`)

토큰은 user_id 와 계정 종류만 담는다(platform.md §1.3). 닉네임·MMR 은 서버 저장소에서 읽는다 — 클라이언트가 보낸 값은
쓰지 않는다. 핸들러는 이 프로토콜에만 의존하므로 users 개편·MMR 저장소(인증·MMR 작업)가 들어와도 구현만 바뀐다.

**임시:** MMR 저장소(`user_game_stats`)가 아직 없어 모두 `mmr_initial` 이다.
"""

from dataclasses import dataclass
from typing import Callable, Optional, Protocol

from sqlalchemy.ext.asyncio import async_sessionmaker

from app.core.config import settings
from app.db.config import get_session_factory, is_db_available
from app.db.repository import UserRepository


@dataclass(frozen=True)
class Identity:
    user_id: int
    nickname: Optional[str]   # None 이면 멀티플레이 불가 (§2 nickname_required)
    mmr: int


class IdentityUnavailable(Exception):
    """신원 저장소에 닿지 못했다 — 클라이언트 잘못이 아니다(재시도 대상)"""


class IdentityDirectory(Protocol):
    async def lookup(self, user_id: int) -> Optional[Identity]:
        """없는 유저면 None. 저장소 장애면 IdentityUnavailable"""
        ...


def _app_session_factory() -> Optional[async_sessionmaker]:
    return get_session_factory() if is_db_available() else None


class DbIdentityDirectory:
    def __init__(self, session_factory: Callable[[], Optional[async_sessionmaker]] = _app_session_factory):
        self._session_factory = session_factory

    async def lookup(self, user_id: int) -> Optional[Identity]:
        factory = self._session_factory()
        if factory is None:
            raise IdentityUnavailable("database unavailable")
        try:
            async with factory() as session:
                user = await UserRepository(session).get_by_id(user_id)
        except Exception as exc:
            raise IdentityUnavailable(type(exc).__name__) from exc
        if user is None:
            return None
        return Identity(user_id=user.id, nickname=user.nickname or None, mmr=settings.mmr_initial)


identity_directory = DbIdentityDirectory()
