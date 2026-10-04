import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from decimal import Decimal
from unittest.mock import AsyncMock, patch
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from parcel_delivery.db.dependencies import get_db_session
from parcel_delivery.db.models import Parcel, ParcelType
from parcel_delivery.db.session import engine
from parcel_delivery.main import app


@asynccontextmanager
async def read_api_client() -> AsyncIterator[tuple[AsyncClient, AsyncSession, UUID]]:
    session_id = uuid4()
    try:
        async with engine.connect() as connection:
            transaction = await connection.begin()
            async with AsyncSession(
                bind=connection,
                expire_on_commit=False,
                join_transaction_mode="create_savepoint",
            ) as db:

                async def override_get_db_session() -> AsyncIterator[AsyncSession]:
                    yield db

                try:
                    with patch.dict(
                        app.dependency_overrides, {get_db_session: override_get_db_session}
                    ):
                        async with AsyncClient(
                            transport=ASGITransport(app=app),
                            base_url="http://test.local",
                            cookies={"session_id": str(session_id)},
                        ) as client:
                            yield client, db, session_id
                finally:
                    await db.close()
                    await transaction.rollback()
    finally:
        await engine.dispose()


async def seed_parcels(db: AsyncSession, session_id: UUID) -> list[Parcel]:
    types = (await db.scalars(select(ParcelType).order_by(ParcelType.id))).all()
    assert len(types) >= 2
    parcels = [
        Parcel(
            name=f"Read API parcel {index}",
            weight=Decimal("1.250"),
            type_id=parcel_type.id,
            content_value_usd=Decimal("100.00"),
            delivery_cost_rub=cost,
            session_id=session_id,
        )
        for index, (parcel_type, cost) in enumerate(
            [(types[0], None), (types[0], Decimal("146.25")), (types[1], None)]
        )
    ]
    db.add_all(parcels)
    await db.flush()
    return parcels


def test_parcel_types_are_public_and_sorted() -> None:
    asyncio.run(_test_parcel_types_are_public_and_sorted())


async def _test_parcel_types_are_public_and_sorted() -> None:
    async with read_api_client() as (client, _, _):
        client.cookies.clear()
        response = await client.get("/parcel-types")

    assert response.status_code == 200
    types = response.json()
    assert {item["name"] for item in types} == {"clothes", "electronics", "misc"}
    assert [item["id"] for item in types] == sorted(item["id"] for item in types)
    assert "set-cookie" not in response.headers


def test_parcel_list_pagination_and_empty_page() -> None:
    asyncio.run(_test_parcel_list_pagination_and_empty_page())


async def _test_parcel_list_pagination_and_empty_page() -> None:
    async with read_api_client() as (client, db, session_id):
        parcels = await seed_parcels(db, session_id)
        response = await client.get("/parcels", params={"limit": 1, "offset": 1})
        assert response.status_code == 200
        assert [item["id"] for item in response.json()] == [parcels[1].id]

        response = await client.get("/parcels", params={"offset": 3})
        assert response.status_code == 200
        assert response.json() == []


@pytest.mark.parametrize("calculated", [None, True, False])
def test_parcel_list_combines_filters_and_session_isolation(calculated: bool | None) -> None:
    asyncio.run(_test_parcel_list_combines_filters_and_session_isolation(calculated))


async def _test_parcel_list_combines_filters_and_session_isolation(
    calculated: bool | None,
) -> None:
    async with read_api_client() as (client, db, session_id):
        parcels = await seed_parcels(db, session_id)
        foreign_parcels = await seed_parcels(db, uuid4())
        params = {"type_id": str(parcels[0].type_id)}
        if calculated is not None:
            params["delivery_cost_calculated"] = str(calculated).lower()
        response = await client.get("/parcels", params=params)
        assert response.status_code == 200
        expected = parcels[:2]
        if calculated is not None:
            expected = [
                item for item in expected if (item.delivery_cost_rub is not None) == calculated
            ]
        ids = [item["id"] for item in response.json()]
        assert ids == [item.id for item in expected]
        assert not set(ids).intersection(item.id for item in foreign_parcels)

        response = await client.get("/parcels", params={"type_id": 2_147_483_647})
        assert response.status_code == 200
        assert response.json() == []


@pytest.mark.parametrize(
    "params",
    [
        {"limit": 0},
        {"limit": 101},
        {"offset": -1},
        {"type_id": 0},
        {"type_id": 2_147_483_648},
        {"type_id": 2**80},
        {"offset": 2_147_483_648},
        {"offset": 2**80},
        {"delivery_cost_calculated": "not-a-bool"},
    ],
)
def test_parcel_list_rejects_invalid_query_parameters(params: dict[str, int | str]) -> None:
    asyncio.run(_test_parcel_list_rejects_invalid_query_parameters(params))


async def _test_parcel_list_rejects_invalid_query_parameters(params: dict[str, int | str]) -> None:
    async with read_api_client() as (client, _, _):
        response = await client.get("/parcels", params=params)
        assert response.status_code == 422
        assert isinstance(response.json()["detail"], list)


def test_get_own_parcel_includes_type_name_and_delivery_cost_display() -> None:
    asyncio.run(_test_get_own_parcel_includes_type_name_and_delivery_cost_display())


async def _test_get_own_parcel_includes_type_name_and_delivery_cost_display() -> None:
    async with read_api_client() as (client, db, session_id):
        parcels = await seed_parcels(db, session_id)
        type_name = await db.scalar(
            select(ParcelType.name).where(ParcelType.id == parcels[0].type_id)
        )
        for parcel, display in zip(parcels[:2], ["Не рассчитано", "146.25"], strict=True):
            response = await client.get(f"/parcels/{parcel.id}")
            assert response.status_code == 200
            body = response.json()
            assert body["id"] == parcel.id
            assert body["name"] == parcel.name
            assert body["type_id"] == parcel.type_id
            assert body["type_name"] == type_name
            assert Decimal(body["weight"]) == parcel.weight
            assert Decimal(body["content_value_usd"]) == parcel.content_value_usd
            assert body["delivery_cost_display"] == display
            if parcel.delivery_cost_rub is None:
                assert body["delivery_cost_rub"] is None
            else:
                assert Decimal(body["delivery_cost_rub"]) == parcel.delivery_cost_rub

        response = await client.get("/parcels")
        assert response.json()[0]["delivery_cost_display"] == "Не рассчитано"


def test_missing_parcel_matches_foreign_parcel_error() -> None:
    asyncio.run(_test_missing_parcel_matches_foreign_parcel_error())


async def _test_missing_parcel_matches_foreign_parcel_error() -> None:
    async with read_api_client() as (client, db, _):
        foreign_parcels = await seed_parcels(db, uuid4())
        for parcel_id in [foreign_parcels[0].id, 2_147_483_647]:
            response = await client.get(f"/parcels/{parcel_id}")
            assert response.status_code == 404
            assert response.json() == {"detail": f"Parcel with id {parcel_id} was not found"}


@pytest.mark.parametrize("parcel_id", [0, -1, 2_147_483_648, 2**63, 2**80])
def test_get_parcel_rejects_non_positive_id(parcel_id: int) -> None:
    asyncio.run(_test_get_parcel_rejects_non_positive_id(parcel_id))


async def _test_get_parcel_rejects_non_positive_id(parcel_id: int) -> None:
    async with read_api_client() as (client, _, _):
        response = await client.get(f"/parcels/{parcel_id}")
        assert response.status_code == 422


@pytest.mark.parametrize("cookie", [None, "invalid-uuid"])
def test_missing_or_invalid_session_cookie_is_replaced(cookie: str | None) -> None:
    asyncio.run(_test_missing_or_invalid_session_cookie_is_replaced(cookie))


async def _test_missing_or_invalid_session_cookie_is_replaced(cookie: str | None) -> None:
    async with read_api_client() as (client, _, _):
        client.cookies.clear()
        if cookie is not None:
            client.cookies.set("session_id", cookie, domain="test.local", path="/")
        response = await client.get("/parcels")
        assert response.status_code == 200
        assert response.json() == []
        assert UUID(client.cookies["session_id"]).version == 4
        assert "HttpOnly" in response.headers["set-cookie"]
        assert "SameSite=lax" in response.headers["set-cookie"]


@pytest.mark.parametrize(
    "overrides",
    [
        {"weight": "0.0001"},
        {"weight": "10000000"},
        {"content_value_usd": "0.001"},
        {"content_value_usd": "10000000000"},
        {"name": "   "},
        {"content_value_usd": "0"},
        {"type_id": 0},
        {"type_id": 2_147_483_648},
        {"type_id": 2**80},
        {"unexpected_field": "not-allowed"},
    ],
)
def test_registration_rejects_invalid_input_before_database_write(
    overrides: dict[str, str | int],
) -> None:
    asyncio.run(_test_registration_rejects_invalid_input_before_database_write(overrides))


async def _test_registration_rejects_invalid_input_before_database_write(
    overrides: dict[str, str | int],
) -> None:
    async with read_api_client() as (client, db, session_id):
        type_id = await db.scalar(select(ParcelType.id).order_by(ParcelType.id).limit(1))
        assert type_id is not None
        payload = {
            "name": "Invalid parcel",
            "weight": "1.250",
            "type_id": type_id,
            "content_value_usd": "100.00",
        }
        payload.update(overrides)
        response = await client.post("/parcels", json=payload)
        assert response.status_code == 422
        assert await db.scalar(select(Parcel.id).where(Parcel.session_id == session_id)) is None


def test_api_accepts_postgresql_integer_upper_bound() -> None:
    asyncio.run(_test_api_accepts_postgresql_integer_upper_bound())


async def _test_api_accepts_postgresql_integer_upper_bound() -> None:
    async with read_api_client() as (client, _, _):
        maximum = 2_147_483_647
        response = await client.get("/parcels", params={"offset": maximum, "type_id": maximum})
        assert response.status_code == 200
        assert response.json() == []
        response = await client.post(
            "/parcels",
            json={
                "name": "Upper boundary type",
                "weight": "1",
                "type_id": maximum,
                "content_value_usd": "1",
            },
        )
        assert response.status_code == 404


def test_registration_returns_generated_id_without_refresh() -> None:
    asyncio.run(_test_registration_returns_generated_id_without_refresh())


async def _test_registration_returns_generated_id_without_refresh() -> None:
    async with read_api_client() as (client, db, _):
        type_id = await db.scalar(select(ParcelType.id).order_by(ParcelType.id).limit(1))
        with patch.object(db, "refresh", new_callable=AsyncMock) as refresh:
            response = await client.post(
                "/parcels",
                json={
                    "name": "No refresh parcel",
                    "weight": "1",
                    "type_id": type_id,
                    "content_value_usd": "1",
                },
            )
        assert response.status_code == 201
        parcel_id = response.json()["id"]
        assert isinstance(parcel_id, int)
        assert await db.scalar(select(Parcel.id).where(Parcel.id == parcel_id)) == parcel_id
        refresh.assert_not_awaited()
