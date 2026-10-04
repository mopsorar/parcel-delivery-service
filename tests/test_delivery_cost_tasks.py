import asyncio
from contextlib import suppress
from unittest.mock import AsyncMock, Mock, call, patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from parcel_delivery.tasks import delivery_costs


def test_delivery_cost_loop_continues_after_failure() -> None:
    asyncio.run(_test_delivery_cost_loop_continues_after_failure())


async def _test_delivery_cost_loop_continues_after_failure() -> None:
    first_db = AsyncMock(spec=AsyncSession)
    first_db.__aenter__.return_value = first_db
    first_db.__aexit__.return_value = False
    second_db = AsyncMock(spec=AsyncSession)
    second_db.__aenter__.return_value = second_db
    second_db.__aexit__.return_value = False
    factory = Mock(side_effect=[first_db, second_db])

    with (
        patch.object(delivery_costs, "session_factory", factory),
        patch.object(
            delivery_costs,
            "calculate_pending_delivery_costs",
            new_callable=AsyncMock,
            side_effect=[RuntimeError("Calculation failed"), 1],
        ) as calculate,
        patch.object(
            delivery_costs.asyncio,
            "sleep",
            new_callable=AsyncMock,
            side_effect=[None, None, asyncio.CancelledError()],
        ) as sleep,
        pytest.raises(asyncio.CancelledError),
    ):
        await delivery_costs.run_delivery_cost_calculation_loop()

    assert factory.call_count == 2
    assert calculate.await_args_list == [call(first_db), call(second_db)]
    assert sleep.await_args_list == [call(300), call(300), call(300)]
    first_db.__aexit__.assert_awaited_once()
    second_db.__aexit__.assert_awaited_once()


def test_delivery_cost_loop_cancellation_closes_active_session() -> None:
    asyncio.run(_test_delivery_cost_loop_cancellation_closes_active_session())


async def _test_delivery_cost_loop_cancellation_closes_active_session() -> None:
    started = asyncio.Event()
    db = AsyncMock(spec=AsyncSession)
    db.__aenter__.return_value = db
    db.__aexit__.return_value = False

    async def blocked_calculation(session: AsyncSession) -> int:
        started.set()
        await asyncio.Event().wait()
        return 0

    with (
        patch.object(delivery_costs, "session_factory", return_value=db),
        patch.object(
            delivery_costs,
            "calculate_pending_delivery_costs",
            new_callable=AsyncMock,
            side_effect=blocked_calculation,
        ) as calculate,
        patch.object(delivery_costs.asyncio, "sleep", new_callable=AsyncMock),
    ):
        task = asyncio.create_task(delivery_costs.run_delivery_cost_calculation_loop())
        try:
            await asyncio.wait_for(started.wait(), timeout=1)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        finally:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task

    calculate.assert_awaited_once_with(db)
    db.__aexit__.assert_awaited_once()
