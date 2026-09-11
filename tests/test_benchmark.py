import json
from contextlib import nullcontext
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

import omniagent.benchmark as module
from omniagent.benchmark import (
    BenchmarkAttempt,
    BenchmarkFailure,
    measure_attempt,
    summarize_attempts,
)

pytestmark = pytest.mark.unit


def fake_app(*, message_status=200, valid_answer=True, cleanup_status=204, create_status=201):
    app = FastAPI()
    app.state.telemetry = SimpleNamespace(local=SimpleNamespace(snapshot=lambda: []))

    @app.post("/api/sessions")
    def create():
        return JSONResponse({"thread_id": "owned"}, status_code=create_status)

    @app.post("/api/sessions/{thread_id}/messages")
    def message(thread_id: str):
        return JSONResponse(
            {
                "status": "completed",
                "result": {"status": "succeeded" if valid_answer else "abstain"},
                "usage": {"model_calls": 2, "total_tokens": 10},
            },
            status_code=message_status,
            headers={"x-trace-id": "trace"},
        )

    @app.delete("/api/sessions/{thread_id}")
    def delete(thread_id: str):
        return JSONResponse({}, status_code=cleanup_status)

    return app


@pytest.mark.parametrize(
    "configuration,stage",
    [
        ({"create_status": 503}, "create_session"),
        ({"message_status": 503}, "message"),
        ({"valid_answer": False}, "correctness"),
        ({"cleanup_status": 500}, "cleanup"),
    ],
)
def test_failed_attempts_are_recorded_without_exception_response_bodies(configuration, stage):
    app = fake_app(**configuration)
    with TestClient(app) as client:
        result = measure_attempt(client, app, "measured")
    assert not result.succeeded
    assert result.error_stage == stage
    assert result.error_type in {"HTTPStatusError", "BenchmarkFailure"}
    assert result.latency_ms is None if stage == "create_session" else result.latency_ms >= 0


def test_failure_denominators_include_failed_attempts_and_exclude_warmups():
    report = summarize_attempts(
        [
            BenchmarkAttempt("warmup", error_type="TimeoutError"),
            BenchmarkAttempt(
                "measured",
                succeeded=True,
                latency_ms=20,
                database_queries=3,
                database_ms=2,
                model_calls=2,
                tokens=10,
            ),
            BenchmarkAttempt("measured", latency_ms=100, error_type="TimeoutError"),
            BenchmarkAttempt("measured", error_stage="create_session"),
        ]
    )
    assert report["attempted"] == 3 and report["failed"] == 2
    assert report["error_rate"] == pytest.approx(2 / 3)
    assert report["warmup_failed"] == 1
    assert report["latency_sample_count"] == 1
    assert report["message_post_success_p95_ms"] == report["p95_ms"] == 20
    assert report["usage_observed_attempts"] == 1
    empty = summarize_attempts([])
    assert empty["error_rate"] is None and empty["p95_ms"] is None


def stub_environment(monkeypatch, app):
    store = MagicMock()
    connection = store.engine.connect.return_value.__enter__.return_value
    connection.execute.return_value.scalar_one.return_value = []
    app.state.store = store
    monkeypatch.setattr(module, "local_mock", lambda _: nullcontext(0))
    monkeypatch.setattr(module, "create_app", lambda *a, **kw: app)
    monkeypatch.setattr(module, "catalog", lambda *a: ([],))
    for name in ("seed", "build_registry", "build_adapters", "authenticate"):
        monkeypatch.setattr(module, name, lambda *a, **kw: None)
    monkeypatch.setattr(module, "manifest", lambda *a, **kw: {})
    monkeypatch.setattr(module, "revision", lambda *a: "fixture")
    monkeypatch.setattr(module, "code_version", lambda: "fixture")


def test_benchmark_persists_every_failed_attempt_before_failing_gate(monkeypatch, tmp_path):
    stub_environment(monkeypatch, fake_app(message_status=503))
    with pytest.raises(BenchmarkFailure, match="measurements saved"):
        module.benchmark("unused", tmp_path, variant="unit-failure", repetitions=5)
    report = json.loads((tmp_path / "benchmark.json").read_text(encoding="utf-8"))
    assert report["passed"] is False
    assert report["attempted"] == report["failed"] == 5
    assert report["warmup_failed"] == 2
    assert report["error_rate"] == 1
    assert len(report["measurements"]) == 5
    assert report["p50_ms"] is None


def test_environment_failure_is_unknown_rate_and_persisted(monkeypatch, tmp_path):
    stub_environment(monkeypatch, fake_app())

    def unavailable(_):
        raise OSError("private connection details")

    monkeypatch.setattr(module, "local_mock", unavailable)
    report = module.benchmark(
        "unused", tmp_path, variant="unit-setup", repetitions=5, raise_on_failure=False
    )
    assert report["environment_error"] == "OSError"
    assert report["attempted"] == 0 and report["error_rate"] is None
    assert "private connection" not in (tmp_path / "benchmark.json").read_text(encoding="utf-8")


def test_successful_benchmark_keeps_old_metric_keys(monkeypatch, tmp_path):
    stub_environment(monkeypatch, fake_app())
    report = module.benchmark("unused", tmp_path, variant="unit-success", repetitions=5)
    assert report["passed"] is True
    assert report["successful"] == report["attempted"] == report["latency_sample_count"] == 5
    assert report["error_rate"] == 0
    assert report["p95_ms"] == report["message_post_success_p95_ms"]
