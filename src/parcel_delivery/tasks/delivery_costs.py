import asyncio
import logging

from parcel_delivery.db.session import session_factory
from parcel_delivery.services.delivery_costs import calculate_pending_delivery_costs

DELIVERY_COST_CALCULATION_INTERVAL_SECONDS = 300

logger = logging.getLogger(__name__)


async def run_delivery_cost_calculation_loop() -> None:
    while True:
        await asyncio.sleep(DELIVERY_COST_CALCULATION_INTERVAL_SECONDS)
        try:
            async with session_factory() as db:
                await calculate_pending_delivery_costs(db)
        except Exception:
            logger.exception("Periodic delivery cost calculation failed")
