from decimal import Decimal

from parcel_delivery.services.delivery_costs import calculate_delivery_cost


def test_calculate_delivery_cost_by_formula() -> None:
    result = calculate_delivery_cost(
        weight=Decimal("2.5"),
        content_value_usd=Decimal("123.45"),
        usd_rub_rate=Decimal("80"),
    )

    assert result == Decimal("198.76")
    assert result.as_tuple().exponent == -2


def test_calculate_delivery_cost_rounds_half_up() -> None:
    result = calculate_delivery_cost(
        weight=Decimal("1"),
        content_value_usd=Decimal("1"),
        usd_rub_rate=Decimal("1.5"),
    )

    assert result == Decimal("0.77")


def test_calculate_delivery_cost_returns_decimal() -> None:
    result = calculate_delivery_cost(
        weight=Decimal("2"),
        content_value_usd=Decimal("100"),
        usd_rub_rate=Decimal("90"),
    )

    assert isinstance(result, Decimal)
