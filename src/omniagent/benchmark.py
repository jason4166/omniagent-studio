"""Fixed local Fake workload with database spans and a real PostgreSQL EXPLAIN."""

import json
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from statistics import mean
from time import perf_counter
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import text

from omniagent.application import create_app
from omniagent.connectors import build_adapters, build_registry, catalog
from omniagent.eval_platform import percentile
from omniagent.identity import authenticate
from omniagent.local_services import local_mock
from omniagent.presets import seed
from omniagent.security_scan import git
from omniagent.semantic_cache import code_version, manifest
from omniagent.session_store import digest


def benchmark(
    database_url: str, output: Path, *, variant: str, repetitions: int = 20
) -> dict[str, object]:
    if not 5 <= repetitions <= 100:
        raise ValueError("Benchmark repetitions must be between 5 and 100")
    measurements = []
    statements: Counter[str] = Counter()
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
                created = client.post("/api/sessions", json={"profile_id": "hr"})
                created.raise_for_status()
                thread_id = created.json()["thread_id"]
                try:
                    start = perf_counter()
                    response = client.post(
                        f"/api/sessions/{thread_id}/messages",
                        json={"message": "年假 leave allowance", "request_key": uuid4().hex},
                    )
                    elapsed = (perf_counter() - start) * 1000
                    response.raise_for_status()
                    data = response.json()
                    if data["status"] != "completed" or data["result"]["status"] != "succeeded":
                        raise RuntimeError("Benchmark correctness gate failed")
                    trace_id = response.headers["x-trace-id"]
                    spans = [
                        item
                        for item in app.state.telemetry.local.snapshot()
                        if item["trace_id"] == trace_id
                    ]
                    database = [item for item in spans if item["name"] == "database"]
                    if index >= 2:
                        statements.update(
                            str(item["attributes"]["statement_hash"]) for item in database
                        )
                        measurements.append(
                            {
                                "latency_ms": elapsed,
                                "database_queries": len(database),
                                "database_ms": sum(float(item["duration_ms"]) for item in database),
                                "trace_id": trace_id,
                                "model_calls": data["usage"]["model_calls"],
                                "tokens": data["usage"]["total_tokens"],
                            }
                        )
                finally:
                    client.delete(f"/api/sessions/{thread_id}").raise_for_status()
    latencies = [float(item["latency_ms"]) for item in measurements]
    report: dict[str, object] = {
        "schema_version": 1,
        "variant": variant,
        "created_at": datetime.now(UTC).isoformat(),
        "git_commit": git(Path.cwd(), "rev-parse", "HEAD").decode().strip(),
        "code_version": code_version(),
        "workload": "new HR thread -> one grounded leave query; validated message POST latency; "
        "two warmups; cache disabled",
        "workload_hash": digest(
            ["hr", "年假 leave allowance", "fake", "cache-disabled", repetitions]
        ),
        "versions": dependencies,
        "repetitions": repetitions,
        "provider": "fake",
        "p50_ms": percentile(latencies, 0.5),
        "p95_ms": percentile(latencies, 0.95),
        "mean_database_queries": mean(float(item["database_queries"]) for item in measurements),
        "mean_database_ms": mean(float(item["database_ms"]) for item in measurements),
        "error_rate": 0,
        "model_calls": sum(int(item["model_calls"]) for item in measurements),
        "tokens": sum(int(item["tokens"]) for item in measurements),
        "cost_microusd": 0,
        "statement_counts": dict(statements.most_common()),
        "explain_profile_lookup": plan,
        "measurements": measurements,
    }
    output.mkdir(parents=True, exist_ok=True)
    (output / "benchmark.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    (output / "benchmark.md").write_text(
        f"# Fake benchmark — {variant}\n\n{report['workload']}\n\n"
        f"- Repetitions: {repetitions}\n- P50: {report['p50_ms']:.3f} ms\n"
        f"- P95: {report['p95_ms']:.3f} ms\n"
        f"- Mean database queries: {report['mean_database_queries']}\n"
        f"- Mean database time: {report['mean_database_ms']:.3f} ms\n"
        f"- Errors: {report['error_rate']}\n- Model calls: {report['model_calls']}\n"
        f"- Fake byte tokens: {report['tokens']}\n- Cost: 0\n\n"
        "The JSON includes exact versions, request trace IDs, query fingerprints and PostgreSQL "
        "EXPLAIN ANALYZE with buffers. Model tokens are synthetic UTF-8 units. These timings are "
        "local observations, not a service-level promise.\n",
        encoding="utf-8",
    )
    return report
