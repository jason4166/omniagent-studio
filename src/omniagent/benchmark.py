"""Bounded serial Fake workload; every attempt, including failures, is recorded."""

import json
import platform
from collections import Counter
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from statistics import mean
from time import perf_counter
from typing import Any, Literal
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import text

from omniagent.application import create_app
from omniagent.connectors import build_adapters, build_registry, catalog
from omniagent.eval_platform import percentile
from omniagent.identity import authenticate
from omniagent.local_services import local_mock
from omniagent.presets import seed
from omniagent.security_scan import revision
from omniagent.semantic_cache import code_version, manifest
from omniagent.session_store import digest


class BenchmarkFailure(RuntimeError):
    """Measurements were persisted, but the correctness gate failed."""


@dataclass
class BenchmarkAttempt:
    phase: Literal["warmup", "measured"]
    succeeded: bool = False
    latency_ms: float | None = None
    database_queries: int | None = None
    database_ms: float | None = None
    trace_id: str | None = None
    model_calls: int | None = None
    tokens: int | None = None
    error_stage: str | None = None
    error_type: str | None = None
    cleanup_failed: bool = False
    statements: dict[str, int] = field(default_factory=dict)


def measure_attempt(
    client: TestClient, app: FastAPI, phase: Literal["warmup", "measured"]
) -> BenchmarkAttempt:
    attempt = BenchmarkAttempt(phase=phase)
    thread_id: str | None = None
    stage = "create_session"
    try:
        created = client.post("/api/sessions", json={"profile_id": "hr"})
        created.raise_for_status()
        thread_id = str(created.json()["thread_id"])
        stage = "message"
        started = perf_counter()
        try:
            response = client.post(
                f"/api/sessions/{thread_id}/messages",
                json={"message": "年假 leave allowance", "request_key": uuid4().hex},
            )
        finally:
            attempt.latency_ms = (perf_counter() - started) * 1000
        response.raise_for_status()
        data = response.json()
        stage = "correctness"
        if data["status"] != "completed" or data["result"]["status"] != "succeeded":
            raise BenchmarkFailure("Message did not produce a successful grounded answer")
        stage = "telemetry"
        attempt.trace_id = response.headers["x-trace-id"]
        database = [
            item
            for item in app.state.telemetry.local.snapshot()
            if item["trace_id"] == attempt.trace_id and item["name"] == "database"
        ]
        attempt.database_queries = len(database)
        attempt.database_ms = sum(float(item["duration_ms"]) for item in database)
        attempt.statements = dict(
            Counter(str(item["attributes"]["statement_hash"]) for item in database)
        )
        attempt.model_calls = int(data["usage"]["model_calls"])
        attempt.tokens = int(data["usage"]["total_tokens"])
        attempt.succeeded = True
    except Exception as exc:
        attempt.error_stage = stage
        attempt.error_type = type(exc).__name__
    finally:
        if thread_id is not None:
            try:
                client.delete(f"/api/sessions/{thread_id}").raise_for_status()
            except Exception as exc:
                attempt.cleanup_failed = True
                attempt.succeeded = False
                if attempt.error_stage is None:
                    attempt.error_stage = "cleanup"
                    attempt.error_type = type(exc).__name__
    return attempt


def summarize_attempts(attempts: list[BenchmarkAttempt]) -> dict[str, Any]:
    measured = [item for item in attempts if item.phase == "measured"]
    successful = [item for item in measured if item.succeeded]
    latency = [item.latency_ms for item in successful if item.latency_ms is not None]
    database = [item for item in successful if item.database_queries is not None]
    errors = sum(not item.succeeded for item in measured)
    statements: Counter[str] = Counter()
    for item in measured:
        statements.update(item.statements)
    p50 = percentile(latency, 0.5) if latency else None
    p95 = percentile(latency, 0.95) if latency else None
    return {
        "attempted": len(measured),
        "successful": len(successful),
        "failed": errors,
        "error_rate": errors / len(measured) if measured else None,
        "error_rate_denominator": len(measured),
        "warmup_attempted": sum(item.phase == "warmup" for item in attempts),
        "warmup_failed": sum(item.phase == "warmup" and not item.succeeded for item in attempts),
        "cleanup_failures": sum(item.cleanup_failed for item in attempts),
        "latency_sample_count": len(latency),
        "message_post_success_p50_ms": p50,
        "message_post_success_p95_ms": p95,
        "p50_ms": p50,
        "p95_ms": p95,
        "mean_database_queries": mean(item.database_queries or 0 for item in database)
        if database
        else None,
        "mean_database_ms": mean(item.database_ms or 0 for item in database) if database else None,
        "database_sample_count": len(database),
        "model_calls": sum(item.model_calls or 0 for item in measured),
        "tokens": sum(item.tokens or 0 for item in measured),
        "usage_observed_attempts": sum(item.model_calls is not None for item in measured),
        "statement_counts": dict(statements.most_common()),
        "measurements": [asdict(item) for item in measured],
        "warmups": [asdict(item) for item in attempts if item.phase == "warmup"],
    }


def benchmark(
    database_url: str,
    output: Path,
    *,
    variant: str,
    repetitions: int = 20,
    raise_on_failure: bool = True,
) -> dict[str, Any]:
    if not 5 <= repetitions <= 100:
        raise ValueError("Benchmark repetitions must be between 5 and 100")
    attempts: list[BenchmarkAttempt] = []
    dependencies: dict[str, object] = {}
    plan: object = None
    environment_error: str | None = None
    try:
        with local_mock(database_url) as port:
            app = create_app(database_url, mock_port=port, rate_limit=5000, cache_enabled=False)
            store = app.state.store
            definitions = catalog("127.0.0.1", port)[0]
            seed(store, definitions)
            actor = authenticate("Bearer local-demo-member")
            dependencies = manifest(
                store,
                store.profile("hr", actor),
                actor,
                build_registry(store, build_adapters("127.0.0.1", port), definitions),
            )
            with store.engine.connect() as db:
                plan = db.execute(
                    text(
                        "EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) "
                        "SELECT * FROM agent_profiles WHERE profile_id = :profile"
                    ),
                    {"profile": "hr"},
                ).scalar_one()
            with TestClient(app, headers={"Authorization": "Bearer local-demo-member"}) as client:
                for index in range(repetitions + 2):
                    attempts.append(
                        measure_attempt(client, app, "warmup" if index < 2 else "measured")
                    )
    except Exception as exc:
        environment_error = type(exc).__name__
    report = {
        "schema_version": 2,
        "variant": variant,
        "created_at": datetime.now(UTC).isoformat(),
        "git_commit": revision(Path.cwd()),
        "code_version": code_version(),
        "environment": {
            "python": platform.python_version(),
            "system": platform.system(),
            "machine": platform.machine(),
            "transport": "in-process-TestClient",
            "concurrency": 1,
        },
        "workload": "new HR thread -> one grounded leave query; serial in-process TestClient; "
        "two warmups; cache disabled",
        "timing_scope": "successful message POST only; excludes creation, cleanup, HTTP server "
        "transport, browser and human waits; not a concurrent load test",
        "workload_hash": digest(
            ["hr", "年假 leave allowance", "fake", "cache-disabled", repetitions]
        ),
        "versions": dependencies,
        "repetitions": repetitions,
        "provider": "fake",
        "cost_microusd": 0,
        "environment_error": environment_error,
        "explain_profile_lookup": plan,
        **summarize_attempts(attempts),
    }
    report["passed"] = (
        environment_error is None
        and report["attempted"] == repetitions
        and report["failed"] == 0
        and report["warmup_failed"] == 0
    )
    output.mkdir(parents=True, exist_ok=True)
    (output / "benchmark.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    (output / "benchmark.md").write_text(
        f"# Fake benchmark — {variant}\n\n{report['workload']}\n\n{report['timing_scope']}\n\n"
        f"- Gate passed: {report['passed']}\n"
        f"- Measured attempts / successes / failures: {report['attempted']} / "
        f"{report['successful']} / {report['failed']}\n"
        f"- Error rate: {report['error_rate']} (denominator {report['error_rate_denominator']})\n"
        f"- Warmup failures: {report['warmup_failed']}\n"
        f"- Environment error: {environment_error}\n"
        f"- Successful message POST P50 / P95: {report['p50_ms']} / {report['p95_ms']} ms "
        f"({report['latency_sample_count']} samples)\n"
        f"- Mean database queries / ms: {report['mean_database_queries']} / "
        f"{report['mean_database_ms']} ({report['database_sample_count']} samples)\n"
        f"- Observed model calls / Fake byte tokens: {report['model_calls']} / {report['tokens']}\n"
        f"- Attempts with observed usage: {report['usage_observed_attempts']}\n\n"
        "The JSON preserves failed attempts and cleanup failures without exception bodies. "
        "Warmups do not enter the measured error-rate denominator. No measured attempts means "
        "an unknown rate, not zero. Legacy p50_ms/p95_ms are compatibility aliases for the "
        "successful message POST distribution. Local observations do not establish an SLA.\n",
        encoding="utf-8",
    )
    if not report["passed"] and raise_on_failure:
        raise BenchmarkFailure(
            f"Benchmark failed; measurements saved to {output / 'benchmark.json'}"
        )
    return report
