"""신원 조회 — users 를 읽는 유일한 경로라 실제 DB 로 확인한다(나머지 WS 테스트는 가짜 신원)"""

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.core.config import settings
from app.services.identity import DbIdentityDirectory, IdentityUnavailable


async def test_lookup_reads_nickname_and_initial_mmr(async_engine, user_repository):
    user, _ = await user_repository.create("미로장인", "pw-1234")
    directory = DbIdentityDirectory(lambda: async_sessionmaker(async_engine, expire_on_commit=False))

    found = await directory.lookup(user.id)
    assert found is not None
    assert (found.user_id, found.nickname, found.mmr) == (user.id, "미로장인", settings.mmr_initial)
    assert await directory.lookup(user.id + 10_000) is None


async def test_no_database_is_unavailable_not_unknown_user():
    """DB 가 없으면 '없는 유저'(4001)가 아니라 저장소 장애다 — 클라이언트 잘못으로 끊지 않는다"""
    with pytest.raises(IdentityUnavailable):
        await DbIdentityDirectory(lambda: None).lookup(1)
