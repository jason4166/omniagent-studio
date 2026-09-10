"""Bounded API ingress and request-local trace context, including streaming lifetimes."""

import hashlib
import json
from collections import OrderedDict, deque
from collections.abc import Callable
from threading import Lock
from time import monotonic
from uuid import UUID, uuid4

import anyio
from opentelemetry.trace import StatusCode
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from omniagent.errors import PlatformError
from omniagent.identity import authenticate
from omniagent.telemetry import Telemetry, span


class RateLimiter:
    def __init__(
        self, limit: int = 240, window: float = 60, *, clock: Callable[[], float] = monotonic
    ) -> None:
        self.limit = limit
        self.window = window
        self.clock = clock
        self.entries: OrderedDict[str, deque[float]] = OrderedDict()
        self.streams: dict[str, int] = {}
        self.lock = Lock()

    def allow(self, key: str) -> bool:
        with self.lock:
            now = self.clock()
            values = self.entries.setdefault(key, deque())
            self.entries.move_to_end(key)
            while values and values[0] <= now - self.window:
                values.popleft()
            if len(values) >= self.limit:
                return False
            values.append(now)
            while len(self.entries) > 1024:
                self.entries.popitem(last=False)
            return True

    def stream(self, key: str, change: int) -> bool:
        with self.lock:
            current = self.streams.get(key, 0)
            if change > 0 and current >= 6:
                return False
            if current + change <= 0:
                self.streams.pop(key, None)
            else:
                self.streams[key] = current + change
            return True


class BoundaryMiddleware:
    MAX_BODY = 1_100_000

    def __init__(self, app: ASGIApp, telemetry: Telemetry, limiter: RateLimiter) -> None:
        self.app = app
        self.telemetry = telemetry
        self.limiter = limiter

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        request_id = str(uuid4())
        path = scope.get("path", "")
        thread_id = ""
        if path.startswith("/api/sessions/"):
            try:
                thread_id = str(UUID(path.split("/")[3]))
            except ValueError:
                pass
        with (
            self.telemetry.activate(request_id=request_id, thread_id=thread_id),
            span("api", http_method=scope["method"]) as current,
        ):
            started = False
            finished = False

            async def output(message: Message) -> None:
                nonlocal started, finished
                if message["type"] == "http.response.body" and not message.get("more_body", False):
                    finished = True
                if message["type"] == "http.response.start":
                    started = True
                    status = message["status"]
                    current.set_attribute("http_status", status)
                    if status >= 400:
                        current.set_status(StatusCode.ERROR)
                    context = current.get_span_context()
                    headers = list(message.get("headers", []))
                    headers.extend(
                        [
                            (b"x-request-id", request_id.encode()),
                            (b"x-trace-id", f"{context.trace_id:032x}".encode()),
                            (b"x-content-type-options", b"nosniff"),
                            (b"cache-control", b"no-store"),
                        ]
                    )
                    message = {**message, "headers": headers}
                await send(message)

            async def reject(status: int, code: str) -> None:
                await output(
                    {
                        "type": "http.response.start",
                        "status": status,
                        "headers": [(b"content-type", b"application/json")],
                    }
                )
                await output(
                    {
                        "type": "http.response.body",
                        "body": json.dumps(
                            {"error": {"code": code, "message": code.replace("_", " ")}}
                        ).encode(),
                    }
                )

            peer = str((scope.get("client") or ("unknown", 0))[0])
            key = hashlib.sha256(peer.encode()).hexdigest()
            if path.startswith("/api/") and not self.limiter.allow(key):
                await reject(429, "rate_limited")
                return
            headers = {k.lower(): v for k, v in scope.get("headers", [])}
            if path.startswith("/api/"):
                try:
                    authenticate(headers.get(b"authorization", b"").decode("ascii"))
                except (PlatformError, UnicodeDecodeError):
                    await reject(401, "authentication_required")
                    return
            try:
                length = int(headers.get(b"content-length", b"0"))
            except ValueError:
                await reject(400, "invalid_content_length")
                return
            if length < 0 or length > self.MAX_BODY:
                await reject(413, "request_too_large")
                return
            body = bytearray()
            try:
                with anyio.fail_after(10):
                    while True:
                        message = await receive()
                        if message["type"] == "http.disconnect":
                            return
                        body.extend(message.get("body", b""))
                        if len(body) > self.MAX_BODY:
                            await reject(413, "request_too_large")
                            return
                        if not message.get("more_body", False):
                            break
            except TimeoutError:
                await reject(408, "request_timeout")
                return
            consumed = False

            async def replay() -> Message:
                nonlocal consumed
                if not consumed:
                    consumed = True
                    return {"type": "http.request", "body": bytes(body), "more_body": False}
                return await receive()

            streaming = path.endswith("/events")
            if streaming and not self.limiter.stream(key, 1):
                await reject(429, "too_many_streams")
                return
            try:
                await self.app(scope, replay, output)
            except Exception:
                current.set_status(StatusCode.ERROR)
                if not started:
                    await reject(500, "internal_error")
                elif not finished:
                    await output({"type": "http.response.body", "body": b"", "more_body": False})
            finally:
                if streaming:
                    self.limiter.stream(key, -1)
