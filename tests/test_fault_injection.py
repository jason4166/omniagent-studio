import asyncio
import os
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.exc import TimeoutError as DatabaseTimeoutError

from omniagent.application import create_app
from omniagent.connectors import catalog
from omniagent.embeddings import FakeEmbedding
from omniagent.local_services import local_mock
from omniagent.middleware import BoundaryMiddleware, RateLimiter
from omniagent.postgres_retrieval import HybridRetriever
from omniagent.presets import seed
from omniagent.telemetry import Telemetry, span

pytestmark = pytest.mark.integration


@pytest.mark.parametrize("dependency", ["embedding", "database"])
def test_transient_retrieval_failure_reserves_each_retry_and_recovers(monkeypatch, dependency):
    url = os.environ.get("OMNIAGENT_TEST_DATABASE_URL")
    if not url:
        pytest.skip("OMNIAGENT_TEST_DATABASE_URL required")
    with local_mock(url) as port:
        app = create_app(url, mock_port=port, cache_enabled=False)
        seed(app.state.store, catalog("127.0.0.1", port)[0])
        target, name = (
            (FakeEmbedding, "embed")
            if dependency == "embedding"
            else (HybridRetriever, "retrieve_hits")
        )
        original = getattr(target, name)
        calls = []

        def flaky(instance, *args, **kwargs):
            calls.append(1)
            if len(calls) == 1:
                raise (
                    TimeoutError("synthetic embedding timeout")
                    if dependency == "embedding"
                    else DatabaseTimeoutError("synthetic pool timeout")
                )
            return original(instance, *args, **kwargs)

        monkeypatch.setattr(target, name, flaky)
        with TestClient(app, headers={"Authorization": "Bearer local-demo-member"}) as client:
            thread = client.post("/api/sessions", json={"profile_id": "hr"}).json()["thread_id"]
            try:
                response = client.post(
                    f"/api/sessions/{thread}/messages",
                    json={"message": "annual leave", "request_key": uuid4().hex},
                )
                assert response.status_code == 200
                data = response.json()
                assert data["status"] == "completed" and data["usage"]["retrieval_calls"] == 2
                assert len(calls) == 2
                telemetry = app.state.telemetry
                with telemetry.activate(request_id="synthetic-database-failure"), span("fault"):
                    with app.state.store.engine.connect() as db:
                        with pytest.raises(DBAPIError):
                            db.execute(text("SELECT 1 / 0"))
                        db.rollback()
                        assert db.scalar(text("SELECT 1")) == 1
                failed = [
                    item
                    for item in telemetry.local.snapshot()
                    if item["attributes"].get("request_id") == "synthetic-database-failure"
                ]
                assert any(
                    item["name"] == "database" and item["status"] == "error" for item in failed
                )
                assert all(item["duration_ms"] >= 0 for item in failed)
            finally:
                assert client.delete(f"/api/sessions/{thread}").status_code == 204


def test_sse_failure_after_headers_closes_stream_and_releases_capacity():
    sent = []

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message):
        sent.append(message)

    async def failed_stream(_scope, _receive, output):
        await output(
            {
                "type": "http.response.start",
                "status": 200,
                "headers": [(b"content-type", b"text/event-stream")],
            }
        )
        await output({"type": "http.response.body", "body": b"id: saved:1\n\n", "more_body": True})
        raise ConnectionError("synthetic stream failure; never serialized")

    telemetry, limiter = Telemetry(), RateLimiter()
    middleware = BoundaryMiddleware(failed_stream, telemetry, limiter)
    asyncio.run(
        middleware(
            {
                "type": "http",
                "method": "GET",
                "path": "/api/events",
                "client": ("local", 1),
                "headers": [(b"authorization", b"Bearer local-demo-member")],
            },
            receive,
            send,
        )
    )
    assert sent[-1] == {"type": "http.response.body", "body": b"", "more_body": False}
    assert limiter.streams == {}
    assert telemetry.local.snapshot()[-1]["status"] == "error"
    telemetry.shutdown()
