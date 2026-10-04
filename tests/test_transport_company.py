import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from decimal import Decimal
from unittest.mock import AsyncMock, Mock, patch
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient, Response
from sqlalchemy import delete, select, text
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession

from parcel_delivery.db.dependencies import get_db_session
from parcel_delivery.db.models import Parcel, ParcelType
from parcel_delivery.db.session import engine, session_factory
from parcel_delivery.main import app
from parcel_delivery.services.parcels import assign_transport_company


@asynccontextmanager
async def assignment_client() -> AsyncIterator[tuple[AsyncClient, AsyncSession, UUID, int]]:
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
                            type_id = await db.scalar(
                                select(ParcelType.id).order_by(ParcelType.id).limit(1)
                            )
                            assert type_id is not None
                            response = await client.post(
                                "/parcels",
                                json={
                                    "name": "Transport assignment test parcel",
                                    "weight": "1.250",
                                    "type_id": type_id,
                                    "content_value_usd": "100.00",
                                },
                            )
                            assert response.status_code == 201
                            yield client, db, session_id, response.json()["id"]
                finally:
                    await db.close()
                    await transaction.rollback()
    finally:
        await engine.dispose()


@pytest.mark.parametrize("company_id", [123, 2**80 + 123])
def test_first_transport_company_assignment_is_persisted(company_id: int) -> None:
    asyncio.run(_test_first_transport_company_assignment_is_persisted(company_id))


async def _test_first_transport_company_assignment_is_persisted(company_id: int) -> None:
    async with assignment_client() as (client, db, _, parcel_id):
        before = await client.get(f"/parcels/{parcel_id}")
        assert before.json()["transport_company_id"] is None

        response = await client.post(
            f"/parcels/{parcel_id}/transport-company", json={"company_id": company_id}
        )
        assert response.status_code == 200
        assert response.json() == {"parcel_id": parcel_id, "transport_company_id": company_id}
        stored_id = await db.scalar(
            select(Parcel.transport_company_id).where(Parcel.id == parcel_id)
        )
        assert isinstance(stored_id, int)
        assert stored_id == company_id

        detail = await client.get(f"/parcels/{parcel_id}")
        listing = await client.get("/parcels")
        assert detail.json()["transport_company_id"] == company_id
        assert listing.json()[0]["transport_company_id"] == company_id


@pytest.mark.parametrize("second_company_id", [123, 456])
def test_assigned_transport_company_cannot_be_changed(second_company_id: int) -> None:
    asyncio.run(_test_assigned_transport_company_cannot_be_changed(second_company_id))


async def _test_assigned_transport_company_cannot_be_changed(second_company_id: int) -> None:
    async with assignment_client() as (client, db, _, parcel_id):
        first = await client.post(
            f"/parcels/{parcel_id}/transport-company", json={"company_id": 123}
        )
        assert first.status_code == 200
        second = await client.post(
            f"/parcels/{parcel_id}/transport-company", json={"company_id": second_company_id}
        )
        assert second.status_code == 409
        assert second.json() == {
            "detail": f"Parcel with id {parcel_id} is already assigned to a transport company"
        }
        assert (
            await db.scalar(select(Parcel.transport_company_id).where(Parcel.id == parcel_id))
            == 123
        )


@pytest.mark.parametrize("company_id", [0, -1, 1.5, True, "123", None])
def test_assignment_rejects_invalid_company_id(company_id: object) -> None:
    asyncio.run(_test_assignment_rejects_invalid_company_id(company_id))


async def _test_assignment_rejects_invalid_company_id(company_id: object) -> None:
    async with assignment_client() as (client, db, _, parcel_id):
        response = await client.post(
            f"/parcels/{parcel_id}/transport-company", json={"company_id": company_id}
        )
        assert response.status_code == 422
        assert (
            await db.scalar(select(Parcel.transport_company_id).where(Parcel.id == parcel_id))
            is None
        )


@pytest.mark.parametrize("assigned", [False, True])
def test_foreign_session_cannot_assign_transport_company(assigned: bool) -> None:
    asyncio.run(_test_foreign_session_cannot_assign_transport_company(assigned))


async def _test_foreign_session_cannot_assign_transport_company(assigned: bool) -> None:
    async with assignment_client() as (client_a, db, session_a, parcel_id):
        if assigned:
            response = await client_a.post(
                f"/parcels/{parcel_id}/transport-company", json={"company_id": 123}
            )
            assert response.status_code == 200

        session_b = uuid4()
        assert session_a != session_b
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test.local",
            cookies={"session_id": str(session_b)},
        ) as client_b:
            response = await client_b.post(
                f"/parcels/{parcel_id}/transport-company", json={"company_id": 456}
            )
        assert response.status_code == 404
        assert response.json() == {"detail": f"Parcel with id {parcel_id} was not found"}
        stored_id = await db.scalar(
            select(Parcel.transport_company_id).where(Parcel.id == parcel_id)
        )
        assert stored_id == (123 if assigned else None)


@pytest.mark.parametrize("missing_id", [2_147_483_647])
def test_assignment_of_nonexistent_parcel_returns_not_found(missing_id: int) -> None:
    asyncio.run(_test_assignment_of_nonexistent_parcel_returns_not_found(missing_id))


async def _test_assignment_of_nonexistent_parcel_returns_not_found(missing_id: int) -> None:
    async with assignment_client() as (client, _, _session_id, _parcel_id):
        response = await client.post(
            f"/parcels/{missing_id}/transport-company", json={"company_id": 123}
        )
        assert response.status_code == 404
        assert response.json() == {"detail": f"Parcel with id {missing_id} was not found"}


@pytest.mark.parametrize("parcel_id", [0, -1, 2_147_483_648, 2**63, 2**80])
def test_assignment_rejects_non_positive_parcel_id(parcel_id: int) -> None:
    asyncio.run(_test_assignment_rejects_non_positive_parcel_id(parcel_id))


async def _test_assignment_rejects_non_positive_parcel_id(parcel_id: int) -> None:
    async with assignment_client() as (client, _, _session_id, _parcel_id):
        response = await client.post(
            f"/parcels/{parcel_id}/transport-company", json={"company_id": 123}
        )
        assert response.status_code == 422


@pytest.mark.parametrize(
    "value", [Decimal("0"), Decimal("-1"), Decimal("1.5"), Decimal("NaN"), Decimal("Infinity")]
)
def test_database_rejects_invalid_transport_company_id(value: Decimal) -> None:
    asyncio.run(_test_database_rejects_invalid_transport_company_id(value))


async def _test_database_rejects_invalid_transport_company_id(value: Decimal) -> None:
    async with assignment_client() as (_, db, _session_id, parcel_id):
        with pytest.raises(IntegrityError):
            async with db.begin_nested():
                # Raw SQL bypasses the request schema and ORM type conversion.
                await db.execute(
                    text("UPDATE parcels SET transport_company_id = :value WHERE id = :parcel_id"),
                    {"value": value, "parcel_id": parcel_id},
                )
        assert (
            await db.scalar(select(Parcel.transport_company_id).where(Parcel.id == parcel_id))
            is None
        )


@pytest.mark.parametrize("failing_operation", ["execute", "commit"])
def test_assignment_rolls_back_database_errors(failing_operation: str) -> None:
    asyncio.run(_test_assignment_rolls_back_database_errors(failing_operation))


async def _test_assignment_rolls_back_database_errors(failing_operation: str) -> None:
    db = AsyncMock(spec=AsyncSession)
    db.execute.return_value = Mock(
        mappings=Mock(
            return_value=Mock(
                one_or_none=Mock(return_value={"parcel_id": 1, "transport_company_id": 123})
            )
        )
    )
    error = SQLAlchemyError("Assignment failed")
    getattr(db, failing_operation).side_effect = error
    with pytest.raises(SQLAlchemyError) as caught:
        await assign_transport_company(db, 1, uuid4(), 123)
    assert caught.value is error
    db.rollback.assert_awaited_once_with()
    db.scalar.assert_not_awaited()


async def wait_until_both_requests_are_blocked(
    gate: AsyncConnection, backend_pids: list[int]
) -> None:
    while True:
        if len(backend_pids) == 2:
            assert len(set(backend_pids)) == 2
            blockers = [
                await gate.scalar(text("SELECT pg_blocking_pids(:pid)"), {"pid": pid})
                for pid in backend_pids
            ]
            if all(blockers):
                return
        await asyncio.sleep(0.01)


@pytest.mark.parametrize("companies", [(101, 202), (2**80 + 1, 2**80 + 2)])
def test_concurrent_assignments_have_exactly_one_winner(companies: tuple[int, int]) -> None:
    asyncio.run(_test_concurrent_assignments_have_exactly_one_winner(companies))


async def _test_concurrent_assignments_have_exactly_one_winner(companies: tuple[int, int]) -> None:
    session_id = uuid4()
    parcel_id: int | None = None
    backend_pids: list[int] = []
    try:
        async with session_factory() as setup:
            type_id = await setup.scalar(select(ParcelType.id).order_by(ParcelType.id).limit(1))
            assert type_id is not None
            parcel = Parcel(
                name=f"Concurrent assignment test {session_id}",
                weight=Decimal("1.250"),
                content_value_usd=Decimal("100.00"),
                delivery_cost_rub=Decimal("10.00"),
                type_id=type_id,
                session_id=session_id,
            )
            setup.add(parcel)
            await setup.flush()
            parcel_id = parcel.id
            # Independent transactions must be able to see the same test row.
            await setup.commit()

        async def independent_session() -> AsyncIterator[AsyncSession]:
            async with session_factory() as db:
                backend_pid = await db.scalar(text("SELECT pg_backend_pid()"))
                assert isinstance(backend_pid, int)
                backend_pids.append(backend_pid)
                yield db

        with patch.dict(app.dependency_overrides, {get_db_session: independent_session}):
            async with (
                AsyncClient(
                    transport=ASGITransport(app=app),
                    base_url="http://test.local",
                    cookies={"session_id": str(session_id)},
                ) as first_client,
                AsyncClient(
                    transport=ASGITransport(app=app),
                    base_url="http://test.local",
                    cookies={"session_id": str(session_id)},
                ) as second_client,
                engine.connect() as gate,
                gate.begin() as gate_transaction,
            ):
                assert await gate.get_isolation_level() == "READ COMMITTED"
                # Hold the row until BOTH real UPDATEs are waiting in PostgreSQL.
                # This controls the test schedule, not the production guarantee.
                await gate.execute(
                    select(Parcel.id).where(Parcel.id == parcel_id).with_for_update()
                )
                requests: list[asyncio.Task[Response]] = [
                    asyncio.create_task(
                        client.post(
                            f"/parcels/{parcel_id}/transport-company",
                            json={"company_id": company_id},
                        )
                    )
                    for client, company_id in zip(
                        [first_client, second_client], companies, strict=True
                    )
                ]
                try:
                    await asyncio.wait_for(
                        wait_until_both_requests_are_blocked(gate, backend_pids), timeout=5
                    )
                    await gate_transaction.rollback()
                    responses = await asyncio.wait_for(asyncio.gather(*requests), timeout=10)
                finally:
                    if gate_transaction.is_active:
                        await gate_transaction.rollback()
                    for request in requests:
                        if not request.done():
                            request.cancel()
                    await asyncio.gather(*requests, return_exceptions=True)

        assert sorted(response.status_code for response in responses) == [200, 409]
        winners = [
            company_id
            for company_id, response in zip(companies, responses, strict=True)
            if response.status_code == 200
        ]
        assert len(winners) == 1
        winner = winners[0]
        successful_response = next(
            response for response in responses if response.status_code == 200
        )
        assert successful_response.json() == {
            "parcel_id": parcel_id,
            "transport_company_id": winner,
        }
        async with session_factory() as verification:
            stored_id = await verification.scalar(
                select(Parcel.transport_company_id).where(Parcel.id == parcel_id)
            )
            assert isinstance(stored_id, int)
            assert stored_id == winner
    finally:
        try:
            if parcel_id is not None:
                async with session_factory() as cleanup:
                    await cleanup.execute(
                        delete(Parcel).where(
                            Parcel.id == parcel_id, Parcel.session_id == session_id
                        )
                    )
                    await cleanup.commit()
        finally:
            await engine.dispose()
