import logging
import time
from typing import Any

import structlog
from starlette.types import ASGIApp, Message, Receive, Scope, Send


def configure_logging(log_level: str = "INFO") -> None:
    """Configure structlog JSON structured logging for the application."""
    level_num = getattr(logging, log_level.strip().upper(), logging.INFO)
    logging.basicConfig(level=level_num, format="%(message)s")
    structlog.configure(
        processors=[
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.stdlib.add_log_level,
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(level_num),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str) -> Any:
    """Return a bound structlog logger."""
    return structlog.get_logger(name)


class RequestLoggingMiddleware:
    """Pure ASGI middleware emitting structured request metadata without body/PII capture."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app
        self.logger = get_logger("http.access")

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        start = time.perf_counter()
        status_code = 500
        request_id = ""
        for key, value in scope.get("headers") or []:
            if key.decode("latin-1").lower() == "x-request-id":
                request_id = value.decode("latin-1", errors="ignore").strip()[:128]
                break

        async def send_wrapper(message: Message) -> None:
            nonlocal status_code, request_id
            if message["type"] == "http.response.start":
                status_code = int(message.get("status", 200))
                if not request_id:
                    for key, value in message.get("headers") or []:
                        if key.decode("latin-1").lower() == "x-request-id":
                            request_id = value.decode("latin-1", errors="ignore").strip()[:128]
                            break
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            duration_ms = round((time.perf_counter() - start) * 1000.0, 2)
            self.logger.info(
                "http_request",
                method=scope.get("method", ""),
                path=scope.get("path", ""),
                status_code=status_code,
                duration_ms=duration_ms,
                request_id=request_id or None,
            )
