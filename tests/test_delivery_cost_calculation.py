import asyncio
from collections.abc import AsyncIterator
from decimal import Decimal
from unittest.mock import AsyncMock, Mock, patch
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select, update
from sqlalchemy.dialects import postgresql
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from parcel_delivery.config import settings
from parcel_delivery.db.dependencies import get_db_session
from parcel_delivery.db.models import Parcel, ParcelType
from parcel_delivery.db.session import engine
from parcel_delivery.main import app
from parcel_delivery.services import delivery_costs


def test_calculate_delivery_costs_updates_only_pending_parcels() -> None:
    asyncio.run(_test_calculate_delivery_costs_updates_only_pending_parcels())


async def _test_calculate_delivery_costs_updates_only_pending_parcels() -> None:
    try:
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
                existing_pending_ids = (
                    await db.scalars(select(Parcel.id).where(Parcel.delivery_cost_rub.is_(None)))
                ).all()

                pending_a = Parcel(
                    name="Pending parcel A",
                    weight=Decimal("2.000"),
                    content_value_usd=Decimal("100.00"),
                    type_id=type_id,
                    session_id=uuid4(),
                )
                pending_b = Parcel(
                    name="Pending parcel B",
                    weight=Decimal("1.250"),
                    content_value_usd=Decimal("100.00"),
                    type_id=type_id,
                    session_id=uuid4(),
                )
                calculated = Parcel(
                    name="Already calculated parcel",
                    weight=Decimal("2.000"),
                    content_value_usd=Decimal("100.00"),
                    delivery_cost_rub=Decimal("0.00"),
                    type_id=type_id,
                    session_id=uuid4(),
                )
                db.add_all([pending_a, pending_b, calculated])
                await db.flush()

                stored_costs_statement = select(Parcel.id, Parcel.delivery_cost_rub).where(
                    Parcel.id.in_([pending_a.id, pending_b.id, calculated.id])
                )
                with (
                    patch.object(
                        delivery_costs,
                        "get_usd_rub_rate",
                        new_callable=AsyncMock,
                        return_value=Decimal("90"),
                    ) as get_rate,
                    patch.object(db, "commit", new_callable=AsyncMock, wraps=db.commit) as commit,
                ):
                    async with AsyncClient(
                        transport=ASGITransport(app=app),
                        base_url="http://test",
                    ) as client:
                        response = await client.post("/parcels/calculate-delivery-costs")

                        assert response.status_code == 200
                        assert response.json() == {"processed_count": len(existing_pending_ids) + 2}
                        get_rate.assert_awaited_once_with()
                        commit.assert_awaited_once_with()
                        stored_costs = dict(
                            (await connection.execute(stored_costs_statement)).all()
                        )
                        assert stored_costs == {
                            pending_a.id: Decimal("180.00"),
                            pending_b.id: Decimal("146.25"),
                            calculated.id: Decimal("0.00"),
                        }

                        get_rate.side_effect = AssertionError(
                            "Exchange rate must not be fetched when no pending parcels remain"
                        )
                        repeated_response = await client.post("/parcels/calculate-delivery-costs")

                        assert repeated_response.status_code == 200
                        assert repeated_response.json() == {"processed_count": 0}
                        get_rate.assert_awaited_once_with()
                        commit.assert_awaited_once_with()
                        assert (
                            dict((await connection.execute(stored_costs_statement)).all())
                            == stored_costs
                        )
            finally:
                app.dependency_overrides.pop(get_db_session, None)
                await db.close()
                await transaction.rollback()
    finally:
        await engine.dispose()


def test_calculate_pending_delivery_costs_selects_with_skip_locked() -> None:
    asyncio.run(_test_calculate_pending_delivery_costs_selects_with_skip_locked())


async def _test_calculate_pending_delivery_costs_selects_with_skip_locked() -> None:
    db = AsyncMock(spec=AsyncSession)
    result = Mock()
    result.all.return_value = []
    db.scalars.return_value = result

    with patch.object(
        delivery_costs, "get_usd_rub_rate", new_callable=AsyncMock, return_value=Decimal("90")
    ):
        await delivery_costs.calculate_pending_delivery_costs(db)

    db.scalars.assert_awaited_once()
    statement = db.scalars.await_args.args[0]
    sql = str(statement.compile(dialect=postgresql.dialect()))
    assert "WHERE parcels.delivery_cost_rub IS NULL" in sql
    assert "FOR UPDATE SKIP LOCKED" in sql
    assert "ORDER BY parcels.id" in sql
    assert "LIMIT" in sql
    assert statement.compile(dialect=postgresql.dialect()).params["param_1"] == (
        settings.delivery_cost_batch_size
    )


def test_calculate_pending_delivery_costs_without_pending_parcels() -> None:
    asyncio.run(_test_calculate_pending_delivery_costs_without_pending_parcels())


async def _test_calculate_pending_delivery_costs_without_pending_parcels() -> None:
    db = AsyncMock(spec=AsyncSession)
    db.scalar.return_value = None
    result = Mock()
    result.all.return_value = []
    db.scalars.return_value = result

    with patch.object(delivery_costs, "get_usd_rub_rate", new_callable=AsyncMock) as get_rate:
        processed_count = await delivery_costs.calculate_pending_delivery_costs(db)

    assert processed_count == 0
    get_rate.assert_not_awaited()
    db.commit.assert_not_awaited()
    db.rollback.assert_awaited_once_with()
    db.scalars.assert_not_awaited()


@pytest.mark.parametrize("failing_operation", ["scalar", "scalars", "commit"])
def test_calculate_pending_delivery_costs_rolls_back_on_database_error(
    failing_operation: str,
) -> None:
    asyncio.run(
        _test_calculate_pending_delivery_costs_rolls_back_on_database_error(failing_operation)
    )


async def _test_calculate_pending_delivery_costs_rolls_back_on_database_error(
    failing_operation: str,
) -> None:
    db = AsyncMock(spec=AsyncSession)
    result = Mock()
    result.all.return_value = [Parcel(weight=Decimal("2.000"), content_value_usd=Decimal("100.00"))]
    db.scalars.return_value = result
    error = SQLAlchemyError("Database operation failed")
    getattr(db, failing_operation).side_effect = error

    with (
        patch.object(
            delivery_costs,
            "get_usd_rub_rate",
            new_callable=AsyncMock,
            return_value=Decimal("90"),
        ),
        pytest.raises(SQLAlchemyError) as caught_error,
    ):
        await delivery_costs.calculate_pending_delivery_costs(db)

    assert caught_error.value is error
    db.rollback.assert_awaited_once_with()


def test_exchange_rate_is_obtained_before_locking_pending_rows() -> None:
    asyncio.run(_test_exchange_rate_is_obtained_before_locking_pending_rows())


async def _test_exchange_rate_is_obtained_before_locking_pending_rows() -> None:
    db = AsyncMock(spec=AsyncSession)
    events: list[str] = []

    async def get_rate() -> Decimal:
        events.append("rate")
        return Decimal("90")

    async def locked_select(statement: object) -> Mock:
        events.append("lock")
        return Mock(all=Mock(return_value=[]))

    db.scalars.side_effect = locked_select
    with patch.object(delivery_costs, "get_usd_rub_rate", side_effect=get_rate):
        assert await delivery_costs.calculate_pending_delivery_costs(db) == 0
    assert events == ["rate", "lock"]
    db.rollback.assert_awaited_once_with()


def test_calculation_limits_each_transaction_to_configured_batch() -> None:
    asyncio.run(_test_calculation_limits_each_transaction_to_configured_batch())


async def _test_calculation_limits_each_transaction_to_configured_batch() -> None:
    try:
        async with engine.connect() as connection:
            # Connection context rolls back this outer transaction even on assertion failure.
            await connection.begin()
            async with AsyncSession(
                bind=connection, expire_on_commit=False, join_transaction_mode="create_savepoint"
            ) as db:
                # Make pre-existing rows ineligible only inside the rollback-only test transaction.
                await db.execute(
                    update(Parcel)
                    .where(Parcel.delivery_cost_rub.is_(None))
                    .values(delivery_cost_rub=Decimal("0"))
                )
                type_id = await db.scalar(select(ParcelType.id).order_by(ParcelType.id).limit(1))
                parcels = [
                    Parcel(
                        name=f"Bounded batch {index}",
                        weight=Decimal("1"),
                        content_value_usd=Decimal("100"),
                        type_id=type_id,
                        session_id=uuid4(),
                    )
                    for index in range(3)
                ]
                db.add_all(parcels)
                await db.flush()
                with (
                    patch.object(settings, "delivery_cost_batch_size", 2),
                    patch.object(
                        delivery_costs,
                        "get_usd_rub_rate",
                        new_callable=AsyncMock,
                        return_value=Decimal("90"),
                    ),
                ):
                    assert await delivery_costs.calculate_pending_delivery_costs(db) == 2
                    costs = dict(
                        (
                            await db.execute(
                                select(Parcel.id, Parcel.delivery_cost_rub).where(
                                    Parcel.id.in_([parcel.id for parcel in parcels])
                                )
                            )
                        ).all()
                    )
                    assert costs == {
                        parcels[0].id: Decimal("135.00"),
                        parcels[1].id: Decimal("135.00"),
                        parcels[2].id: None,
                    }
                    assert await delivery_costs.calculate_pending_delivery_costs(db) == 1
    finally:
        await engine.dispose()
