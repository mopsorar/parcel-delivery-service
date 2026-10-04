import asyncio
from decimal import Decimal
from unittest.mock import patch

import httpx
import pytest

from parcel_delivery.integrations import exchange_rates


def test_external_rate_uses_decimal_and_nominal() -> None:
    asyncio.run(_test_external_rate_uses_decimal_and_nominal())


async def _test_external_rate_uses_decimal_and_nominal() -> None:
    def respond(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            content=b'{"Valute":{"USD":{"Value":8324.54,"Nominal":100}}}',
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(respond))
    with patch.object(exchange_rates.httpx, "AsyncClient", return_value=client):
        result = await exchange_rates.get_usd_rub_rate()

    assert result == Decimal("83.2454")
    assert isinstance(result, Decimal)


@pytest.mark.parametrize("error_type", [httpx.ConnectError, httpx.ReadTimeout])
def test_network_error_is_wrapped_and_logged(
    error_type: type[httpx.RequestError],
    caplog: pytest.LogCaptureFixture,
) -> None:
    asyncio.run(_test_network_error_is_wrapped_and_logged(error_type))

    assert "USD/RUB exchange rate HTTP request failed" in caplog.text


async def _test_network_error_is_wrapped_and_logged(
    error_type: type[httpx.RequestError],
) -> None:
    def fail(request: httpx.Request) -> httpx.Response:
        raise error_type("External API unavailable", request=request)

    client = httpx.AsyncClient(transport=httpx.MockTransport(fail))
    with (
        patch.object(exchange_rates.httpx, "AsyncClient", return_value=client),
        pytest.raises(exchange_rates.ExchangeRateError) as caught_error,
    ):
        await exchange_rates.get_usd_rub_rate()

    assert not isinstance(caught_error.value, httpx.HTTPError)


def test_http_error_is_wrapped_without_logging_response_body(
    caplog: pytest.LogCaptureFixture,
) -> None:
    asyncio.run(_test_http_error_is_wrapped_without_logging_response_body())

    assert "USD/RUB exchange rate HTTP request failed" in caplog.text
    assert "sensitive-response-body" not in caplog.text


async def _test_http_error_is_wrapped_without_logging_response_body() -> None:
    def respond(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, text="sensitive-response-body")

    client = httpx.AsyncClient(transport=httpx.MockTransport(respond))
    with (
        patch.object(exchange_rates.httpx, "AsyncClient", return_value=client),
        pytest.raises(exchange_rates.ExchangeRateError),
    ):
        await exchange_rates.get_usd_rub_rate()


@pytest.mark.parametrize(
    "content",
    [
        b"not-json",
        b'{"Valute":{}}',
        b'{"Valute":{"USD":{"Value":83.2454,"Nominal":0}}}',
        b'{"Valute":{"USD":{"Value":"NaN","Nominal":1}}}',
        b'{"Valute":{"USD":{"Value":"1e9999999","Nominal":1}}}',
    ],
)
def test_invalid_response_raises_custom_error(content: bytes) -> None:
    asyncio.run(_test_invalid_response_raises_custom_error(content))


async def _test_invalid_response_raises_custom_error(content: bytes) -> None:
    def respond(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=content)

    client = httpx.AsyncClient(transport=httpx.MockTransport(respond))
    with (
        patch.object(exchange_rates.httpx, "AsyncClient", return_value=client),
        pytest.raises(exchange_rates.InvalidExchangeRateResponseError),
    ):
        await exchange_rates.get_usd_rub_rate()
