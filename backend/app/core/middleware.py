import time
import uuid
from collections import defaultdict, deque

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.config import Settings


class SecurityHeadersMiddleware:
    """Pure ASGI middleware injecting X-Request-ID and baseline security headers."""

    def __init__(self, app: ASGIApp, settings: Settings) -> None:
        self.app = app
        self.settings = settings

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request_id: str | None = None
        for key, value in scope.get("headers") or []:
            if key.decode("latin-1").lower() == "x-request-id":
                candidate = value.decode("latin-1", errors="ignore").strip()[:128]
                if candidate:
                    request_id = candidate
                    break
        resolved_id = request_id or str(uuid.uuid4())

        async def send_wrapper(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = list(message.get("headers") or [])
                existing = {k.lower() for k, _ in headers}

                def _set_header(name: bytes, val: bytes) -> None:
                    if name.lower() not in existing:
                        headers.append((name, val))
                        existing.add(name.lower())

                _set_header(b"x-request-id", resolved_id.encode("latin-1"))
                _set_header(b"x-content-type-options", b"nosniff")
                _set_header(b"x-frame-options", b"DENY")
                _set_header(b"referrer-policy", b"strict-origin-when-cross-origin")
                _set_header(
                    b"permissions-policy",
                    b"camera=(), microphone=(), geolocation=()",
                )
                if self.settings.app_env.strip().lower() == "production":
                    _set_header(
                        b"strict-transport-security",
                        b"max-age=31536000; includeSubDomains",
                    )
                message = {**message, "headers": headers}
            await send(message)

        await self.app(scope, receive, send_wrapper)


class RateLimitMiddleware:
    """Pure ASGI sliding-window rate limiter keyed by client IP."""

    def __init__(self, app: ASGIApp, settings: Settings) -> None:
        self.app = app
        self.settings = settings
        self._window_seconds = 60.0
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    def _client_key(self, scope: Scope) -> str:
        for key, value in scope.get("headers") or []:
            if key.decode("latin-1").lower() == "x-forwarded-for":
                first = value.decode("latin-1", errors="ignore").split(",")[0].strip()
                if first:
                    return first
        client = scope.get("client")
        if isinstance(client, tuple) and client:
            return str(client[0])
        return "unknown"

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or not self.settings.rate_limit_enabled:
            await self.app(scope, receive, send)
            return

        path = str(scope.get("path", ""))
        if path.startswith(f"{self.settings.api_v1_prefix}/health"):
            await self.app(scope, receive, send)
            return

        limit = max(1, int(self.settings.rate_limit_requests_per_minute))
        now = time.monotonic()
        cutoff = now - self._window_seconds
        bucket = self._hits[self._client_key(scope)]
        while bucket and bucket[0] <= cutoff:
            bucket.popleft()

        if len(bucket) >= limit:
            retry_after = max(1, int(self._window_seconds - (now - bucket[0])))
            body = b'{"detail":"Rate limit exceeded. Try again shortly."}'
            await send(
                {
                    "type": "http.response.start",
                    "status": 429,
                    "headers": [
                        (b"content-type", b"application/json"),
                        (b"retry-after", str(retry_after).encode("ascii")),
                        (b"x-ratelimit-limit", str(limit).encode("ascii")),
                        (b"x-ratelimit-remaining", b"0"),
                    ],
                }
            )
            await send({"type": "http.response.body", "body": body})
            return

        bucket.append(now)
        remaining = max(0, limit - len(bucket))

        async def send_wrapper(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = list(message.get("headers") or [])
                existing = {k.lower() for k, _ in headers}
                if b"x-ratelimit-limit" not in existing:
                    headers.append((b"x-ratelimit-limit", str(limit).encode("ascii")))
                if b"x-ratelimit-remaining" not in existing:
                    headers.append((b"x-ratelimit-remaining", str(remaining).encode("ascii")))
                message = {**message, "headers": headers}
            await send(message)

        await self.app(scope, receive, send_wrapper)
