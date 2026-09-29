import asyncio
from collections.abc import AsyncIterator
from uuid import uuid4

from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from parcel_delivery.db.dependencies import get_db_session
from parcel_delivery.db.models import Parcel, ParcelType
from parcel_delivery.db.session import engine
from parcel_delivery.main import app


def test_register_parcel() -> None:
    asyncio.run(_test_register_parcel())


async def _test_register_parcel() -> None:
    async with engine.connect() as connection:
        transaction = await connection.begin()
        db = AsyncSession(
            bind=connection,
            expire_on_commit=False,
            join_transaction_mode="create_savepoint",
        )

        async def override_get_db_session() -> AsyncIterator[AsyncSession]:
            yield db

        app.dependency_overrides[get_db_session] = override_get_db_session

        try:
            type_id = await db.scalar(select(ParcelType.id).order_by(ParcelType.id).limit(1))
            assert type_id is not None

            async with AsyncClient(
                transport=ASGITransport(app=app),
                base_url="http://test",
            ) as client:
                response = await client.post(
                    "/parcels",
                    json={
                        "name": "Test parcel",
                        "weight": "1.250",
                        "type_id": type_id,
                        "content_value_usd": "100.00",
                    },
                )

            assert response.status_code == 201
            parcel_id = response.json()["id"]
            assert isinstance(parcel_id, int)

            stored_parcel_id = await connection.scalar(
                select(Parcel.id).where(Parcel.id == parcel_id)
            )
            assert stored_parcel_id == parcel_id
        finally:
            app.dependency_overrides.pop(get_db_session, None)
            await db.close()
            await transaction.rollback()

    await engine.dispose()


def test_register_parcel_with_unknown_type() -> None:
    asyncio.run(_test_register_parcel_with_unknown_type())


async def _test_register_parcel_with_unknown_type() -> None:
    async with engine.connect() as connection:
        transaction = await connection.begin()
        db = AsyncSession(
            bind=connection,
            expire_on_commit=False,
            join_transaction_mode="create_savepoint",
        )

        async def override_get_db_session() -> AsyncIterator[AsyncSession]:
            yield db

        app.dependency_overrides[get_db_session] = override_get_db_session

        try:
            existing_type_ids = set((await db.scalars(select(ParcelType.id))).all())
            missing_type_id = next(
                candidate
                for candidate in range(1, len(existing_type_ids) + 2)
                if candidate not in existing_type_ids
            )
            assert (
                await db.scalar(select(ParcelType.id).where(ParcelType.id == missing_type_id))
                is None
            )

            parcel_name = f"Unknown type parcel {uuid4()}"

            async with AsyncClient(
                transport=ASGITransport(app=app),
                base_url="http://test",
            ) as client:
                response = await client.post(
                    "/parcels",
                    json={
                        "name": parcel_name,
                        "weight": "1.250",
                        "type_id": missing_type_id,
                        "content_value_usd": "100.00",
                    },
                )

            assert response.status_code == 404
            assert response.json() == {
                "detail": f"Parcel type with id {missing_type_id} was not found"
            }
            assert await db.scalar(select(Parcel.id).where(Parcel.name == parcel_name)) is None
        finally:
            app.dependency_overrides.pop(get_db_session, None)
            await db.close()
            await transaction.rollback()

    await engine.dispose()


def test_register_parcel_with_non_positive_weight() -> None:
    asyncio.run(_test_register_parcel_with_non_positive_weight())


async def _test_register_parcel_with_non_positive_weight() -> None:
    async with engine.connect() as connection:
        transaction = await connection.begin()
        db = AsyncSession(
            bind=connection,
            expire_on_commit=False,
            join_transaction_mode="create_savepoint",
        )

        async def override_get_db_session() -> AsyncIterator[AsyncSession]:
            yield db

        app.dependency_overrides[get_db_session] = override_get_db_session

        try:
            type_id = await db.scalar(select(ParcelType.id).order_by(ParcelType.id).limit(1))
            assert type_id is not None

            parcel_name = f"Non-positive weight parcel {uuid4()}"

            async with AsyncClient(
                transport=ASGITransport(app=app),
                base_url="http://test",
            ) as client:
                response = await client.post(
                    "/parcels",
                    json={
                        "name": parcel_name,
                        "weight": "0",
                        "type_id": type_id,
                        "content_value_usd": "100.00",
                    },
                )

            assert response.status_code == 422
            assert await db.scalar(select(Parcel.id).where(Parcel.name == parcel_name)) is None
        finally:
            app.dependency_overrides.pop(get_db_session, None)
            await db.close()
            await transaction.rollback()

    await engine.dispose()
