import asyncio
import logging
from decimal import Decimal
from unittest.mock import AsyncMock, Mock, patch

import pytest
from redis.exceptions import ConnectionError

from parcel_delivery.config import settings
from parcel_delivery.integrations.redis import redis_client
from parcel_delivery.services import exchange_rates


@pytest.mark.parametrize("failing_operation", ["get", "set"])
def test_exchange_rate_cache_failure_still_returns_external_rate(
    failing_operation: str,
    caplog: pytest.LogCaptureFixture,
) -> None:
    asyncio.run(_test_exchange_rate_cache_failure_still_returns_external_rate(failing_operation))

    assert f"Redis {failing_operation.upper()} failed" in caplog.text
    assert any(record.levelno >= logging.WARNING for record in caplog.records)


async def _test_exchange_rate_cache_failure_still_returns_external_rate(
    failing_operation: str,
) -> None:
    cache = Mock(get=AsyncMock(return_value=None), set=AsyncMock())
    getattr(cache, failing_operation).side_effect = ConnectionError("Redis unavailable")
    rate = Decimal("83.2454")

    with (
        patch.object(exchange_rates, "redis_client", cache),
        patch.object(
            exchange_rates, "fetch_usd_rub_rate", new_callable=AsyncMock, return_value=rate
        ) as fetch,
    ):
        result = await exchange_rates.get_usd_rub_rate()

    assert result == rate
    assert isinstance(result, Decimal)
    fetch.assert_awaited_once_with()
    cache.get.assert_awaited_once_with(exchange_rates.USD_RUB_CACHE_KEY)
    cache.set.assert_awaited_once_with(
        exchange_rates.USD_RUB_CACHE_KEY,
        str(rate),
        ex=settings.exchange_rate_cache_ttl_seconds,
    )


def test_exchange_rate_cache_hit_does_not_call_external_api() -> None:
    asyncio.run(_test_exchange_rate_cache_hit_does_not_call_external_api())


async def _test_exchange_rate_cache_hit_does_not_call_external_api() -> None:
    cache = Mock(get=AsyncMock(return_value="83.2454"), set=AsyncMock())
    with (
        patch.object(exchange_rates, "redis_client", cache),
        patch.object(exchange_rates, "fetch_usd_rub_rate", new_callable=AsyncMock) as fetch,
    ):
        result = await exchange_rates.get_usd_rub_rate()

    assert result == Decimal("83.2454")
    assert isinstance(result, Decimal)
    fetch.assert_not_awaited()
    cache.set.assert_not_awaited()


@pytest.mark.parametrize("cached_value", ["invalid", "NaN", "Infinity", "0", "-1", b"\xff"])
def test_invalid_cached_rate_is_refreshed(cached_value: str | bytes) -> None:
    asyncio.run(_test_invalid_cached_rate_is_refreshed(cached_value))


async def _test_invalid_cached_rate_is_refreshed(cached_value: str | bytes) -> None:
    cache = Mock(get=AsyncMock(return_value=cached_value), set=AsyncMock())
    rate = Decimal("83.2454")
    with (
        patch.object(exchange_rates, "redis_client", cache),
        patch.object(
            exchange_rates, "fetch_usd_rub_rate", new_callable=AsyncMock, return_value=rate
        ) as fetch,
    ):
        result = await exchange_rates.get_usd_rub_rate()

    assert result == rate
    fetch.assert_awaited_once_with()
    cache.set.assert_awaited_once()


def test_undecodable_redis_value_uses_external_api(caplog: pytest.LogCaptureFixture) -> None:
    asyncio.run(_test_undecodable_redis_value_uses_external_api())
    assert "Redis GET failed" in caplog.text


async def _test_undecodable_redis_value_uses_external_api() -> None:
    cache = Mock(get=AsyncMock(), set=AsyncMock())
    cache.get.side_effect = UnicodeDecodeError("utf-8", b"\xff", 0, 1, "invalid start byte")
    rate = Decimal("90")
    with (
        patch.object(exchange_rates, "redis_client", cache),
        patch.object(
            exchange_rates, "fetch_usd_rub_rate", new_callable=AsyncMock, return_value=rate
        ) as fetch,
    ):
        assert await exchange_rates.get_usd_rub_rate() == rate
    fetch.assert_awaited_once_with()
    cache.set.assert_awaited_once_with(
        exchange_rates.USD_RUB_CACHE_KEY,
        "90",
        ex=settings.exchange_rate_cache_ttl_seconds,
    )


def test_redis_client_does_not_retry() -> None:
    assert redis_client.get_retry().get_retries() == 0
