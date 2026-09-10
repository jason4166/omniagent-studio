import asyncio
import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from omniagent.middleware import BoundaryMiddleware, RateLimiter
from omniagent.redaction import contains_secret, redact, redact_text
from omniagent.telemetry import Telemetry

pytestmark = pytest.mark.security


def test_rate_limit_and_stream_limit_are_bounded_without_sleep():
    clock = [0.0]
    limiter = RateLimiter(limit=2, window=60, clock=lambda: clock[0])
    assert limiter.allow("client") and limiter.allow("client")
    assert not limiter.allow("client")
    clock[0] = 60
    assert limiter.allow("client")
    assert all(limiter.stream("client", 1) for _ in range(6))
    assert not limiter.stream("client", 1)
    limiter.stream("client", -1)
    assert limiter.stream("client", 1)


def test_ingress_auth_size_limit_and_trace_headers():
    app = FastAPI()
    telemetry = Telemetry()
    app.add_middleware(BoundaryMiddleware, telemetry=telemetry, limiter=RateLimiter(limit=4))

    @app.post("/api/echo")
    async def endpoint():
        return {"ok": True}

    with TestClient(app) as client:
        assert client.post("/api/echo").status_code == 401
        response = client.post("/api/echo", headers={"Authorization": "Bearer local-demo-member"})
        assert response.status_code == 200
        assert len(response.headers["x-trace-id"]) == 32
        assert response.headers["x-content-type-options"] == "nosniff"
        assert (
            client.post(
                "/api/echo",
                headers={"Authorization": "Bearer local-demo-member", "Content-Length": "1100001"},
            ).status_code
            == 413
        )
    telemetry.shutdown()


def test_chunked_request_cannot_escape_the_body_limit():
    sent = []

    async def receive():
        return {"type": "http.request", "body": b"x" * 600000, "more_body": True}

    async def send(message):
        sent.append(message)

    async def endpoint(*_args):
        pytest.fail("Oversized request reached the application")

    telemetry = Telemetry()
    middleware = BoundaryMiddleware(endpoint, telemetry, RateLimiter())
    asyncio.run(
        middleware(
            {
                "type": "http",
                "path": "/api/upload",
                "method": "POST",
                "headers": [(b"authorization", b"Bearer local-demo-member")],
                "client": ("local", 1),
            },
            receive,
            send,
        )
    )
    assert sent[0]["status"] == 413
    telemetry.shutdown()


def test_secret_pii_and_hidden_reasoning_redaction(monkeypatch):
    synthetic = "test-runtime-credential-" + "x" * 20
    monkeypatch.setenv("OMNIAGENT_PROVIDER_API_KEY", synthetic)
    value = {
        "api_key": synthetic,
        "text": f"{synthetic} alice@example.invalid 13800138000 <think>private reasoning</think>",
        "nested": [{"reasoning_content": "private chain"}],
    }
    redacted = json.dumps(redact(value))
    assert all(
        item not in redacted
        for item in [synthetic, "alice@", "13800138000", "private reasoning", "private chain"]
    )
    assert contains_secret(synthetic)
    assert redact_text("C-100 P-200 warranty 24 months") == "C-100 P-200 warranty 24 months"
