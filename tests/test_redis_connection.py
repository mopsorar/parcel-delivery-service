import asyncio

from parcel_delivery.integrations.redis import redis_client


def test_redis_connection() -> None:
    asyncio.run(_test_redis_connection())


async def _test_redis_connection() -> None:
    try:
        assert await redis_client.ping() is True
    finally:
        await redis_client.aclose()
