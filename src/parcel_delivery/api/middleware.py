import logging
import re
from time import perf_counter
from uuid import uuid4

from starlette.datastructures import Headers, MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from parcel_delivery.logging_config import request_id_context

logger = logging.getLogger(__name__)
REQUEST_ID_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", re.ASCII)


class RequestLoggingMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        supplied_request_id = Headers(scope=scope).get("X-Request-ID", "")
        request_id = (
            supplied_request_id
            if len(supplied_request_id) <= 128 and REQUEST_ID_PATTERN.fullmatch(supplied_request_id)
            else str(uuid4())
        )
        scope.setdefault("state", {})["request_id"] = request_id
        token = request_id_context.set(request_id)
        started = perf_counter()
        status_code = 500

        async def send_with_request_id(message: Message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message["status"]
                MutableHeaders(scope=message)["X-Request-ID"] = request_id
            await send(message)

        try:
            await self.app(scope, receive, send_with_request_id)
        except Exception:
            logger.exception(
                "Unhandled HTTP error method=%s path=%r",
                scope["method"],
                scope["path"],
                extra={"request_id": request_id},
            )
            raise
        finally:
            try:
                if scope["path"] != "/health":
                    duration_ms = (perf_counter() - started) * 1000
                    logger.info(
                        "HTTP request method=%s path=%r status=%d duration_ms=%.2f",
                        scope["method"],
                        scope["path"],
                        status_code,
                        duration_ms,
                        extra={
                            "request_id": request_id,
                            "method": scope["method"],
                            "path": scope["path"],
                            "status_code": status_code,
                            "duration_ms": duration_ms,
                        },
                    )
            finally:
                request_id_context.reset(token)
