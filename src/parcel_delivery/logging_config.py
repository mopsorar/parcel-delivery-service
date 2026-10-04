import logging
import traceback
from contextvars import ContextVar
from logging.config import dictConfig
from types import TracebackType

from sqlalchemy.exc import SQLAlchemyError

from parcel_delivery.config import settings

request_id_context: ContextVar[str] = ContextVar("request_id", default="-")


class RequestIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id_context.get()
        return True


class SafeExceptionFormatter(logging.Formatter):
    def formatException(
        self,
        exc_info: tuple[type[BaseException], BaseException, TracebackType | None],
    ) -> str:
        if isinstance(exc_info[1], SQLAlchemyError):
            stack = "".join(traceback.format_tb(exc_info[2]))
            return f"{stack}{type(exc_info[1]).__name__}: database operation failed"
        return super().formatException(exc_info)


def configure_logging() -> None:
    level = settings.log_level.upper()
    dictConfig(
        {
            "version": 1,
            "disable_existing_loggers": False,
            "filters": {"request_id": {"()": RequestIdFilter}},
            "formatters": {
                "standard": {
                    "()": SafeExceptionFormatter,
                    "format": (
                        "%(asctime)s %(levelname)s %(name)s request_id=%(request_id)r %(message)s"
                    ),
                }
            },
            "handlers": {
                "console": {
                    "class": "logging.StreamHandler",
                    "formatter": "standard",
                    "filters": ["request_id"],
                }
            },
            "root": {"level": level, "handlers": ["console"]},
            "loggers": {
                "uvicorn": {"level": level, "handlers": [], "propagate": True},
                "uvicorn.error": {"level": level, "handlers": [], "propagate": True},
                "uvicorn.access": {"handlers": [], "propagate": False},
                "httpx": {"level": "WARNING"},
                "httpcore": {"level": "WARNING"},
                "sqlalchemy.engine": {"level": "WARNING"},
            },
        }
    )
