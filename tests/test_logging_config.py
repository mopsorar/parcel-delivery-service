import logging
import sys
from unittest.mock import patch

from sqlalchemy.exc import StatementError

from parcel_delivery import logging_config
from parcel_delivery.config import settings


def test_logging_config_uses_configured_level_and_disables_duplicate_access_logs() -> None:
    with (
        patch.object(settings, "log_level", "debug"),
        patch.object(logging_config, "dictConfig") as configure,
    ):
        logging_config.configure_logging()

    config = configure.call_args.args[0]
    assert config["root"]["level"] == "DEBUG"
    assert config["loggers"]["uvicorn.access"]["handlers"] == []
    assert config["loggers"]["uvicorn.access"]["propagate"] is False
    assert config["handlers"]["console"]["filters"] == ["request_id"]


def test_logging_filter_adds_request_id_and_resets_context() -> None:
    previous_request_id = logging_config.request_id_context.get()
    token = logging_config.request_id_context.set("request-123")
    try:
        record = logging.makeLogRecord({"msg": "Operation completed"})
        assert logging_config.RequestIdFilter().filter(record) is True
        assert record.request_id == "request-123"
    finally:
        logging_config.request_id_context.reset(token)

    assert logging_config.request_id_context.get() == previous_request_id


def test_database_error_formatting_does_not_expose_sensitive_details() -> None:
    error = StatementError(
        "Database rejected sensitive-password",
        "INSERT INTO parcels VALUES (:session_id)",
        {"session_id": "full-sensitive-session-id"},
        ValueError("Database row includes sensitive-password"),
    )
    try:
        raise error
    except StatementError:
        record = logging.makeLogRecord(
            {"msg": "Database request failed", "exc_info": sys.exc_info()}
        )

    formatter = logging_config.SafeExceptionFormatter("%(message)s")
    output = formatter.format(record)
    assert "StatementError" in output
    assert "sensitive-password" not in output
    assert "full-sensitive-session-id" not in output
    assert "INSERT INTO" not in output
