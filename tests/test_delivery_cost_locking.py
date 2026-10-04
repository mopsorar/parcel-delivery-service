import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from decimal import Decimal
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from sqlalchemy import delete, select, text
from sqlalchemy.exc import SQLAlchemyError

from parcel_delivery.config import settings
from parcel_delivery.db.models import Parcel, ParcelType
from parcel_delivery.db.session import engine, session_factory
from parcel_delivery.services import delivery_costs


@asynccontextmanager
async def pending_test_row() -> AsyncIterator[int]:
    owner = uuid4()
    parcel_id: int | None = None
    try:
        async with session_factory() as setup:
            type_id = await setup.scalar(select(ParcelType.id).order_by(ParcelType.id).limit(1))
            assert type_id is not None
            parcel = Parcel(
                name=f"Delivery locking test {owner}",
                weight=Decimal("1"),
                content_value_usd=Decimal("100"),
                type_id=type_id,
                session_id=owner,
            )
            setup.add(parcel)
            await setup.flush()
            parcel_id = parcel.id
            await setup.commit()

        async with engine.connect() as gate, gate.begin():
            # Do not process existing user rows. A third transaction only shields them
            # during this test; the two workers still execute real production queries.
            await gate.execute(
                select(Parcel.id)
                .where(Parcel.delivery_cost_rub.is_(None), Parcel.session_id != owner)
                .with_for_update(skip_locked=True)
            )
            yield parcel_id
    finally:
        try:
            if parcel_id is not None:
                async with session_factory() as cleanup:
                    await cleanup.execute(
                        delete(Parcel).where(Parcel.id == parcel_id, Parcel.session_id == owner)
                    )
                    await cleanup.commit()
        finally:
            await engine.dispose()


def test_two_workers_do_not_process_the_same_pending_row() -> None:
    asyncio.run(_test_two_workers_do_not_process_the_same_pending_row())


async def _test_two_workers_do_not_process_the_same_pending_row() -> None:
    async with (
        pending_test_row() as parcel_id,
        session_factory() as first,
        session_factory() as second,
    ):
        first_pid = await first.scalar(text("SELECT pg_backend_pid()"))
        second_pid = await second.scalar(text("SELECT pg_backend_pid()"))
        assert first_pid != second_pid
        locked = asyncio.Event()
        release = asyncio.Event()
        original_commit = first.commit

        async def hold_commit() -> None:
            locked.set()
            await release.wait()
            await original_commit()

        with (
            patch.object(settings, "delivery_cost_batch_size", 1),
            patch.object(
                delivery_costs,
                "get_usd_rub_rate",
                new_callable=AsyncMock,
                return_value=Decimal("90"),
            ),
            patch.object(first, "commit", side_effect=hold_commit),
        ):
            task = asyncio.create_task(delivery_costs.calculate_pending_delivery_costs(first))
            try:
                await asyncio.wait_for(locked.wait(), timeout=5)
                # The first calculation still owns the row lock and has not committed.
                assert (
                    await asyncio.wait_for(
                        delivery_costs.calculate_pending_delivery_costs(second), timeout=5
                    )
                    == 0
                )
                release.set()
                assert await asyncio.wait_for(task, timeout=5) == 1
                assert await delivery_costs.calculate_pending_delivery_costs(second) == 0
            finally:
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)

        assert await second.scalar(
            select(Parcel.delivery_cost_rub).where(Parcel.id == parcel_id)
        ) == Decimal("135.00")


@pytest.mark.parametrize("failure", ["rollback", "cancellation"])
def test_rollback_or_cancellation_releases_row_for_next_worker(failure: str) -> None:
    asyncio.run(_test_rollback_or_cancellation_releases_row_for_next_worker(failure))


async def _test_rollback_or_cancellation_releases_row_for_next_worker(failure: str) -> None:
    async with (
        pending_test_row() as parcel_id,
        session_factory() as first,
        session_factory() as second,
    ):
        locked = asyncio.Event()
        fail = asyncio.Event()

        async def failing_commit() -> None:
            locked.set()
            await fail.wait()
            raise SQLAlchemyError("Simulated commit failure before flush")

        with (
            patch.object(settings, "delivery_cost_batch_size", 1),
            patch.object(
                delivery_costs,
                "get_usd_rub_rate",
                new_callable=AsyncMock,
                return_value=Decimal("90"),
            ),
            patch.object(first, "commit", side_effect=failing_commit),
            patch.object(
                first, "rollback", new_callable=AsyncMock, wraps=first.rollback
            ) as rollback,
        ):
            task = asyncio.create_task(delivery_costs.calculate_pending_delivery_costs(first))
            try:
                await asyncio.wait_for(locked.wait(), timeout=5)
                assert (
                    await asyncio.wait_for(
                        delivery_costs.calculate_pending_delivery_costs(second), timeout=5
                    )
                    == 0
                )
                if failure == "cancellation":
                    task.cancel()
                    with pytest.raises(asyncio.CancelledError):
                        await task
                else:
                    fail.set()
                    with pytest.raises(SQLAlchemyError):
                        await asyncio.wait_for(task, timeout=5)
                rollback.assert_awaited_once_with()
                assert not first.in_transaction()
                assert (
                    await second.scalar(
                        select(Parcel.delivery_cost_rub).where(Parcel.id == parcel_id)
                    )
                    is None
                )
                # Keep the first session OPEN: success proves explicit rollback released
                # the lock, rather than relying on its eventual context-manager cleanup.
                assert (
                    await asyncio.wait_for(
                        delivery_costs.calculate_pending_delivery_costs(second), timeout=5
                    )
                    == 1
                )
            finally:
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)

        assert await second.scalar(
            select(Parcel.delivery_cost_rub).where(Parcel.id == parcel_id)
        ) == Decimal("135.00")
