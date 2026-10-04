import asyncio
from unittest.mock import AsyncMock, Mock, patch

import pytest

from parcel_delivery import main


@pytest.mark.parametrize("redis_close_fails", [False, True])
def test_lifespan_stops_task_and_closes_resources(redis_close_fails: bool) -> None:
    asyncio.run(_test_lifespan_stops_task_and_closes_resources(redis_close_fails))


async def _test_lifespan_stops_task_and_closes_resources(redis_close_fails: bool) -> None:
    started = asyncio.Event()
    events: list[str] = []

    async def background_loop() -> None:
        try:
            started.set()
            await asyncio.Event().wait()
        finally:
            events.append("task_stopped")

    async def close_redis() -> None:
        events.append("redis_closed")
        if redis_close_fails:
            raise RuntimeError("Redis close failed")

    async def dispose_engine() -> None:
        events.append("engine_disposed")

    engine_dispose = AsyncMock(side_effect=dispose_engine)
    with (
        patch.object(main, "configure_logging") as configure_logging,
        patch.object(main, "run_delivery_cost_calculation_loop", background_loop),
        patch.object(
            main.redis_client, "aclose", new_callable=AsyncMock, side_effect=close_redis
        ) as redis_close,
        patch.object(main, "engine", Mock(dispose=engine_dispose)),
    ):
        if redis_close_fails:
            with pytest.raises(RuntimeError, match="Redis close failed"):
                async with main.lifespan(main.app):
                    await asyncio.wait_for(started.wait(), timeout=1)
        else:
            async with main.lifespan(main.app):
                await asyncio.wait_for(started.wait(), timeout=1)

    assert events == ["task_stopped", "redis_closed", "engine_disposed"]
    configure_logging.assert_called_once_with()
    redis_close.assert_awaited_once_with()
    engine_dispose.assert_awaited_once_with()
