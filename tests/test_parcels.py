import asyncio
from collections.abc import AsyncIterator, Awaitable
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from parcel_delivery.db.dependencies import get_db_session
from parcel_delivery.db.models import Parcel, ParcelType
from parcel_delivery.db.session import engine
from parcel_delivery.main import app


async def dispose_engine_after(test: Awaitable[None]) -> None:
    try:
        await test
    finally:
        # Pool connections must never survive the asyncio.run() event loop that owns them.
        await engine.dispose()


def test_register_parcel() -> None:
    asyncio.run(dispose_engine_after(_test_register_parcel()))


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


def test_register_parcel_with_unknown_type() -> None:
    asyncio.run(dispose_engine_after(_test_register_parcel_with_unknown_type()))


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


def test_register_parcel_with_non_positive_weight() -> None:
    asyncio.run(dispose_engine_after(_test_register_parcel_with_non_positive_weight()))


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


def test_list_parcels_isolated_by_session() -> None:
    asyncio.run(dispose_engine_after(_test_list_parcels_isolated_by_session()))


async def _test_list_parcels_isolated_by_session() -> None:
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
            ) as client_a:
                response_a = await client_a.post(
                    "/parcels",
                    json={
                        "name": "Session A parcel",
                        "weight": "1.250",
                        "type_id": type_id,
                        "content_value_usd": "100.00",
                    },
                )
                assert response_a.status_code == 201
                parcel_a_id = response_a.json()["id"]

                async with AsyncClient(
                    transport=ASGITransport(app=app),
                    base_url="http://test",
                ) as client_b:
                    response_b = await client_b.post(
                        "/parcels",
                        json={
                            "name": "Session B parcel",
                            "weight": "2.500",
                            "type_id": type_id,
                            "content_value_usd": "200.00",
                        },
                    )
                    assert response_b.status_code == 201
                    parcel_b_id = response_b.json()["id"]

                response = await client_a.get("/parcels")

            assert response.status_code == 200
            parcel_ids = [parcel["id"] for parcel in response.json()]
            assert parcel_ids == [parcel_a_id]
            assert parcel_b_id not in parcel_ids
        finally:
            app.dependency_overrides.pop(get_db_session, None)
            await db.close()
            await transaction.rollback()


def test_get_parcel_from_another_session_returns_not_found() -> None:
    asyncio.run(dispose_engine_after(_test_get_parcel_from_another_session_returns_not_found()))


async def _test_get_parcel_from_another_session_returns_not_found() -> None:
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

            parcel_name = f"Session A private parcel {uuid4()}"
            async with AsyncClient(
                transport=ASGITransport(app=app),
                base_url="http://test",
            ) as client_a:
                create_response = await client_a.post(
                    "/parcels",
                    json={
                        "name": parcel_name,
                        "weight": "1.250",
                        "type_id": type_id,
                        "content_value_usd": "100.00",
                    },
                )
                assert create_response.status_code == 201
                parcel_id = create_response.json()["id"]
                session_a_id = client_a.cookies.get("session_id")

            async with AsyncClient(
                transport=ASGITransport(app=app),
                base_url="http://test",
            ) as client_b:
                list_response = await client_b.get("/parcels")
                assert list_response.status_code == 200
                response = await client_b.get(f"/parcels/{parcel_id}")
                session_b_id = client_b.cookies.get("session_id")

            assert session_a_id is not None
            assert session_b_id is not None
            assert session_a_id != session_b_id
            assert response.status_code == 404
            assert response.json() == {"detail": f"Parcel with id {parcel_id} was not found"}
            assert parcel_name not in response.text
        finally:
            app.dependency_overrides.pop(get_db_session, None)
            await db.close()
            await transaction.rollback()


def test_failed_assertion_does_not_leak_pool_connections_to_next_event_loop() -> None:
    async def fail() -> None:
        async with engine.connect() as connection:
            await connection.scalar(select(1))
            raise AssertionError("Simulated API assertion failure")

    async def succeed() -> None:
        async with engine.connect() as connection:
            assert await connection.scalar(select(1)) == 1

    original_pool = engine.pool
    with pytest.raises(AssertionError, match="Simulated API assertion failure"):
        asyncio.run(dispose_engine_after(fail()))
    assert engine.pool is not original_pool
    replacement_pool = engine.pool
    asyncio.run(dispose_engine_after(succeed()))
    assert engine.pool is not replacement_pool
