import logging
from decimal import Decimal, DecimalException

import httpx

CBR_DAILY_RATES_URL = "https://www.cbr-xml-daily.ru/daily_json.js"
REQUEST_TIMEOUT_SECONDS = 5.0

logger = logging.getLogger(__name__)


class ExchangeRateError(Exception):
    pass


class InvalidExchangeRateResponseError(ExchangeRateError):
    pass


async def get_usd_rub_rate() -> Decimal:
    try:
        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT_SECONDS) as client:
            response = await client.get(CBR_DAILY_RATES_URL)
            response.raise_for_status()
    except httpx.HTTPError as error:
        logger.exception("USD/RUB exchange rate HTTP request failed")
        raise ExchangeRateError("Unable to retrieve USD/RUB exchange rate") from error

    try:
        data = response.json(parse_float=Decimal)
        usd = data["Valute"]["USD"]
        value = Decimal(str(usd["Value"]))
        nominal = Decimal(str(usd["Nominal"]))

        if not value.is_finite() or value <= 0:
            raise ValueError("USD value must be a positive finite number")
        if not nominal.is_finite() or nominal <= 0:
            raise ValueError("USD nominal must be a positive finite number")
        rate = value / nominal
        if not rate.is_finite() or rate <= 0:
            raise ValueError("USD/RUB rate must be a positive finite number")
    except (KeyError, TypeError, ValueError, DecimalException) as error:
        logger.exception("External API returned an invalid USD/RUB exchange rate response")
        raise InvalidExchangeRateResponseError(
            "CBR response does not contain a valid USD exchange rate"
        ) from error

    return rate
