import pytest
from pydantic import ValidationError

from parcel_delivery.config import Settings


def make_settings(**overrides: object) -> Settings:
    values = {
        "log_level": "INFO",
        "db_host": "localhost",
        "db_port": 5432,
        "db_name": "test",
        "db_user": "test",
        "db_password": "test-only",
        "redis_host": "localhost",
        "redis_port": 6379,
        "redis_db": 0,
        "exchange_rate_cache_ttl_seconds": 3600,
        "delivery_cost_batch_size": 100,
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("db_port", 0),
        ("db_port", 65536),
        ("redis_port", 0),
        ("redis_port", 65536),
        ("redis_db", -1),
        ("exchange_rate_cache_ttl_seconds", 0),
        ("exchange_rate_cache_ttl_seconds", -1),
        ("delivery_cost_batch_size", 0),
        ("delivery_cost_batch_size", 10001),
        ("log_level", "VERBOSE"),
        ("log_level", ""),
        ("log_level", "20"),
    ],
)
def test_invalid_settings_fail_at_creation(field: str, value: object) -> None:
    with pytest.raises(ValidationError) as caught:
        make_settings(**{field: value})
    assert field in {error["loc"][0] for error in caught.value.errors()}


@pytest.mark.parametrize("port", [1, 65535])
def test_port_boundaries_are_valid(port: int) -> None:
    config = make_settings(db_port=port, redis_port=port)
    assert config.db_port == config.redis_port == port


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("debug", "DEBUG"),
        (" INFO ", "INFO"),
        ("warn", "WARNING"),
        ("fatal", "CRITICAL"),
        ("ERROR", "ERROR"),
        ("NOTSET", "NOTSET"),
    ],
)
def test_logging_level_is_validated_and_normalized(value: str, expected: str) -> None:
    assert make_settings(log_level=value).log_level == expected


def test_positive_cache_and_batch_boundaries_are_valid() -> None:
    config = make_settings(
        exchange_rate_cache_ttl_seconds=1, redis_db=0, delivery_cost_batch_size=1
    )
    assert config.exchange_rate_cache_ttl_seconds == config.delivery_cost_batch_size == 1
