from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession

from parcel_delivery.db.session import session_factory


async def get_db_session() -> AsyncGenerator[AsyncSession]:
    async with session_factory() as session:
        yield session
