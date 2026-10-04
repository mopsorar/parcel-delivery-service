import logging
from decimal import Decimal, InvalidOperation

from redis.exceptions import RedisError

from parcel_delivery.config import settings
from parcel_delivery.integrations.exchange_rates import get_usd_rub_rate as fetch_usd_rub_rate
from parcel_delivery.integrations.redis import redis_client

USD_RUB_CACHE_KEY = "exchange_rate:usd_rub"

logger = logging.getLogger(__name__)


async def get_usd_rub_rate() -> Decimal:
    try:
        cached_rate = await redis_client.get(USD_RUB_CACHE_KEY)
    except (RedisError, UnicodeDecodeError):
        logger.warning("Redis GET failed; fetching USD/RUB from external API", exc_info=True)
        cached_rate = None

    if cached_rate is not None:
        try:
            rate = Decimal(cached_rate)
            if rate.is_finite() and rate > 0:
                return rate
        except (InvalidOperation, TypeError, ValueError):
            pass
        logger.warning("Invalid cached USD/RUB rate; fetching from external API")

    rate = await fetch_usd_rub_rate()
    try:
        await redis_client.set(
            USD_RUB_CACHE_KEY,
            str(rate),
            ex=settings.exchange_rate_cache_ttl_seconds,
        )
    except RedisError:
        logger.warning("Redis SET failed; returning fetched USD/RUB rate", exc_info=True)
    return rate
