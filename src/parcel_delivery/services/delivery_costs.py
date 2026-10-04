import asyncio
import logging
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from parcel_delivery.config import settings
from parcel_delivery.db.models import Parcel
from parcel_delivery.integrations.exchange_rates import ExchangeRateError
from parcel_delivery.services.exchange_rates import get_usd_rub_rate

logger = logging.getLogger(__name__)


def calculate_delivery_cost(
    weight: Decimal,
    content_value_usd: Decimal,
    usd_rub_rate: Decimal,
) -> Decimal:
    delivery_cost = (weight * Decimal("0.5") + content_value_usd * Decimal("0.01")) * usd_rub_rate
    return delivery_cost.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


async def calculate_pending_delivery_costs(db: AsyncSession) -> int:
    logger.info("Delivery cost calculation started")
    try:
        pending_id = await db.scalar(
            select(Parcel.id).where(Parcel.delivery_cost_rub.is_(None)).limit(1)
        )
        if pending_id is None:
            await db.rollback()
            logger.info("Delivery cost calculation completed processed_count=0")
            return 0

        usd_rub_rate = await get_usd_rub_rate()
        statement = (
            select(Parcel)
            .where(Parcel.delivery_cost_rub.is_(None))
            .order_by(Parcel.id)
            .limit(settings.delivery_cost_batch_size)
            .with_for_update(skip_locked=True)
        )
        parcels = (await db.scalars(statement)).all()
        if not parcels:
            await db.rollback()
            logger.info("Delivery cost calculation completed processed_count=0")
            return 0

        for parcel in parcels:
            parcel.delivery_cost_rub = calculate_delivery_cost(
                parcel.weight,
                parcel.content_value_usd,
                usd_rub_rate,
            )

        await db.commit()
    except (SQLAlchemyError, ExchangeRateError, asyncio.CancelledError):
        await db.rollback()
        raise

    processed_count = len(parcels)
    logger.info("Delivery cost calculation completed processed_count=%d", processed_count)
    return processed_count
