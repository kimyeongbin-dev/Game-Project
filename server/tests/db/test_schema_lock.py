"""스키마 생성 직렬화 — 워커 여럿이 빈 DB 에 동시에 create_all 해도 전부 성공한다 (M3 7단계 다중 워커 실측 X1)

실제 PostgreSQL 이 필요하다(advisory lock 은 DB 기능이다). 실측에서는 워커 2개 중 하나가 유일키 충돌로 DB 없이 떴다.
"""

import asyncio

from sqlalchemy.ext.asyncio import create_async_engine

from app.db.config import Base, create_schema
from tests.conftest import TEST_DATABASE_URL


async def test_concurrent_schema_creation_all_succeed():
    engines = [create_async_engine(TEST_DATABASE_URL) for _ in range(3)]
    try:
        for _ in range(3):   # 경합은 확률적이다 — 여러 번 겹쳐 본다
            async with engines[0].begin() as conn:
                await conn.run_sync(Base.metadata.drop_all)

            async def create(engine):
                async with engine.begin() as conn:
                    await create_schema(conn)

            results = await asyncio.gather(*(create(e) for e in engines), return_exceptions=True)
            assert [r for r in results if isinstance(r, Exception)] == []
    finally:
        async with engines[0].begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
        for e in engines:
            await e.dispose()
