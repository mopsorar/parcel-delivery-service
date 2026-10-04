from redis.asyncio import Redis
from redis.asyncio.retry import Retry
from redis.backoff import NoBackoff

from parcel_delivery.config import settings

redis_client = Redis(
    host=settings.redis_host,
    port=settings.redis_port,
    db=settings.redis_db,
    decode_responses=True,
    socket_connect_timeout=5.0,
    socket_timeout=5.0,
    retry=Retry(NoBackoff(), 0),
)
