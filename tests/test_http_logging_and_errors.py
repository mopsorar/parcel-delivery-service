import asyncio
import logging
from collections.abc import AsyncIterator
from decimal import Decimal
from unittest.mock import AsyncMock, Mock, patch
from uuid import UUID

import httpx
import pytest
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from parcel_delivery import main
from parcel_delivery.db.dependencies import get_db_session
from parcel_delivery.db.models import Parcel
from parcel_delivery.integrations import exchange_rates as integration
from parcel_delivery.services import exchange_rates


def test_response_has_generated_request_id() -> None:
    asyncio.run(_test_response_has_generated_request_id())


async def _test_response_has_generated_request_id() -> None:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=main.app),
        base_url="http://test",
    ) as client:
        first = await client.get("/health")
        second = await client.get("/health")

    assert first.status_code == 200
    assert UUID(first.headers["X-Request-ID"]).version == 4
    assert first.headers["X-Request-ID"] != second.headers["X-Request-ID"]


def test_response_preserves_supplied_request_id() -> None:
    asyncio.run(_test_response_preserves_supplied_request_id())


async def _test_response_preserves_supplied_request_id() -> None:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=main.app),
        base_url="http://test",
    ) as client:
        response = await client.get("/health", headers={"X-Request-ID": "client-request-123"})

    assert response.status_code == 200
    assert response.headers["X-Request-ID"] == "client-request-123"


@pytest.mark.parametrize(
    "request_id", ["", "a" * 129, "bad id", "bad\nid", "bad\rid", "bad/id", b"\xff"]
)
def test_invalid_request_id_is_replaced(request_id: str | bytes) -> None:
    asyncio.run(_test_invalid_request_id_is_replaced(request_id))


async def _test_invalid_request_id_is_replaced(request_id: str | bytes) -> None:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=main.app), base_url="http://test"
    ) as client:
        response = await client.get("/health", headers={"X-Request-ID": request_id})
    assert response.status_code == 200
    assert UUID(response.headers["X-Request-ID"]).version == 4


@pytest.mark.parametrize("request_id", ["a", "a" * 128, "Client_123.trace-id"])
def test_valid_request_id_boundaries_are_preserved(request_id: str) -> None:
    asyncio.run(_test_valid_request_id_boundaries_are_preserved(request_id))


async def _test_valid_request_id_boundaries_are_preserved(request_id: str) -> None:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=main.app), base_url="http://test"
    ) as client:
        response = await client.get("/health", headers={"X-Request-ID": request_id})
    assert response.headers["X-Request-ID"] == request_id


def test_access_log_contains_metadata_without_query_or_cookies(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO, logger="parcel_delivery.api.middleware")
    asyncio.run(_test_access_log_contains_metadata_without_query_or_cookies())

    records = [
        record for record in caplog.records if record.name == "parcel_delivery.api.middleware"
    ]
    assert len(records) == 1
    record = records[0]
    assert record.method == "GET"
    assert record.path == "/missing-route"
    assert record.status_code == 404
    assert record.duration_ms >= 0
    assert record.request_id == "access-request-123"
    assert "sensitive-cookie-value" not in caplog.text
    assert "sensitive-api-key" not in caplog.text


async def _test_access_log_contains_metadata_without_query_or_cookies() -> None:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=main.app),
        base_url="http://test",
        cookies={"session_id": "sensitive-cookie-value"},
    ) as client:
        response = await client.get(
            "/missing-route?api_key=sensitive-api-key",
            headers={"X-Request-ID": "access-request-123"},
        )

    assert response.status_code == 404
    assert response.headers["X-Request-ID"] == "access-request-123"


def test_health_does_not_write_access_log(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO, logger="parcel_delivery.api.middleware")
    asyncio.run(_test_response_has_generated_request_id())

    assert not any(record.name == "parcel_delivery.api.middleware" for record in caplog.records)


def test_manual_calculation_returns_503_when_external_api_fails() -> None:
    asyncio.run(_test_manual_calculation_returns_503_when_external_api_fails())


async def _test_manual_calculation_returns_503_when_external_api_fails() -> None:
    db = AsyncMock(spec=AsyncSession)
    db.scalars.return_value = Mock(
        all=Mock(return_value=[Parcel(weight=Decimal("1"), content_value_usd=Decimal("100"))])
    )

    async def override_get_db_session() -> AsyncIterator[AsyncSession]:
        yield db

    def fail(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("External API unavailable", request=request)

    network_client = httpx.AsyncClient(transport=httpx.MockTransport(fail))
    api_client = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=main.app),
        base_url="http://test",
    )
    cache = Mock(get=AsyncMock(return_value=None), set=AsyncMock())
    with (
        patch.dict(main.app.dependency_overrides, {get_db_session: override_get_db_session}),
        patch.object(exchange_rates, "redis_client", cache),
        patch.object(integration.httpx, "AsyncClient", return_value=network_client),
    ):
        async with api_client:
            response = await api_client.post(
                "/parcels/calculate-delivery-costs",
                headers={"X-Request-ID": "failed-rate-request"},
            )

    assert response.status_code == 503
    assert response.json() == {"detail": "Unable to retrieve USD/RUB exchange rate"}
    assert response.headers["X-Request-ID"] == "failed-rate-request"
    assert "ConnectError" not in response.text
    db.rollback.assert_awaited_once_with()
    db.commit.assert_not_awaited()
    cache.set.assert_not_awaited()


@pytest.mark.parametrize("error_type", [SQLAlchemyError, RuntimeError])
def test_unexpected_calculation_errors_return_500(error_type: type[Exception]) -> None:
    asyncio.run(_test_unexpected_calculation_errors_return_500(error_type))


async def _test_unexpected_calculation_errors_return_500(error_type: type[Exception]) -> None:
    db = AsyncMock(spec=AsyncSession)
    db.scalar.side_effect = error_type("Failure detail must not leak to the response")

    async def override_get_db_session() -> AsyncIterator[AsyncSession]:
        yield db

    with patch.dict(main.app.dependency_overrides, {get_db_session: override_get_db_session}):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=main.app, raise_app_exceptions=False),
            base_url="http://test",
        ) as client:
            response = await client.post(
                "/parcels/calculate-delivery-costs",
                headers={"X-Request-ID": "failed-server-request"},
            )

    assert response.status_code == 500
    assert response.json() == {"detail": "Internal server error"}
    assert response.headers["X-Request-ID"] == "failed-server-request"
    assert "Failure detail" not in response.text
