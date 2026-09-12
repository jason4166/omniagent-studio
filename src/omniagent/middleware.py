"""Bounded API ingress and request-local trace context, including streaming lifetimes."""

import hashlib
import hmac
import json
from collections import OrderedDict, deque
from collections.abc import Callable
from threading import Lock
from time import monotonic
from urllib.parse import urlsplit
from uuid import UUID, uuid4

import anyio
from opentelemetry.trace import StatusCode
from sqlalchemy.exc import SQLAlchemyError
from starlette.requests import Request
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from omniagent.access import AccessService, csrf_token
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

    def __init__(
        self,
        app: ASGIApp,
        telemetry: Telemetry,
        limiter: RateLimiter,
        access: AccessService | None = None,
    ) -> None:
        self.app = app
        self.telemetry = telemetry
        self.limiter = limiter
        self.access = access

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
            if (
                path.startswith("/api/")
                and (self.access is None or self.access.settings.mode == "dev")
                and not self.limiter.allow(key)
            ):
                await reject(429, "rate_limited")
                return
            headers = {k.lower(): v for k, v in scope.get("headers", [])}
            settings = self.access.settings if self.access else None
            password_mode = settings is not None and settings.mode == "password"
            if password_mode and settings is not None:
                if (
                    path not in {"/health", "/ready"}
                    and headers.get(b"host", b"").decode("latin1")
                    != urlsplit(settings.origin).netloc
                ):
                    await reject(400, "invalid_host")
                    return
                if scope["method"] not in {"GET", "HEAD", "OPTIONS"}:
                    if headers.get(b"origin", b"").decode("latin1") != settings.origin:
                        await reject(403, "invalid_origin")
                        return
                    if headers.get(b"sec-fetch-site") == b"cross-site":
                        await reject(403, "invalid_origin")
                        return
            if path.startswith("/api/"):
                try:
                    if password_mode and self.access is not None and settings is not None:
                        await anyio.to_thread.run_sync(
                            self.access.reserve, [("ingress:global", 1, 1200)], 60
                        )
                        if path == "/api/auth/options":
                            if scope["method"] != "GET":
                                await reject(405, "method_not_allowed")
                                return
                        elif path != "/api/auth/login":
                            token = Request(scope).cookies.get(settings.cookie_name, "")
                            actor = await anyio.to_thread.run_sync(self.access.actor, token)
                            scope.setdefault("state", {})["actor"] = actor
                            key = actor.user_id
                            if scope["method"] not in {
                                "GET",
                                "HEAD",
                                "OPTIONS",
                            } and not hmac.compare_digest(
                                headers.get(b"x-csrf-token", b"").decode("latin1"),
                                csrf_token(token),
                            ):
                                await reject(403, "invalid_csrf")
                                return
                            await anyio.to_thread.run_sync(
                                self.access.reserve,
                                [
                                    ("requests:" + key, 1, self.limiter.limit),
                                    ("requests:global", 1, 3600),
                                ],
                                60,
                            )
                            if path == "/api/sessions" and scope["method"] == "POST":
                                await anyio.to_thread.run_sync(
                                    self.access.reserve, [("sessions:" + key, 1, 100)]
                                )
                        elif scope["method"] != "POST" or not headers.get(
                            b"content-type", b""
                        ).startswith(b"application/json"):
                            await reject(400, "invalid_login_request")
                            return
                    elif path != "/api/auth/options" or scope["method"] != "GET":
                        actor = authenticate(headers.get(b"authorization", b"").decode("ascii"))
                        scope.setdefault("state", {})["actor"] = actor
                except PlatformError as exc:
                    await reject(exc.status_code, exc.code.value)
                    return
                except SQLAlchemyError:
                    await reject(503, "dependency_unavailable")
                    return
                except UnicodeDecodeError:
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
            lease_id = ""
            if streaming and password_mode and self.access is not None:
                try:
                    lease_id = await anyio.to_thread.run_sync(self.access.open_stream, actor)
                except PlatformError as exc:
                    await reject(exc.status_code, exc.code.value)
                    return
                except SQLAlchemyError:
                    await reject(503, "dependency_unavailable")
                    return
            if streaming and not password_mode and not self.limiter.stream(key, 1):
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
                if streaming and not password_mode:
                    self.limiter.stream(key, -1)
                if lease_id and self.access is not None:
                    with anyio.CancelScope(shield=True):
                        try:
                            await anyio.to_thread.run_sync(self.access.close_stream, lease_id)
                        except SQLAlchemyError:
                            current.set_status(StatusCode.ERROR)
