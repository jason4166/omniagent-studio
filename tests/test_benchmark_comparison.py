import runpy
from pathlib import Path

import pytest


@pytest.mark.parametrize("failure", ["environment", "missing_version", "failed_attempt"])
def test_benchmark_does_not_compute_improvement_under_unverified_conditions(failure):
    compare = runpy.run_path(str(Path("scripts/compare_benchmark.py")))["compare_reports"]
    baseline = {
        "workload_hash": "fixed",
        "versions": {"profile": "v1"},
        "environment": {"system": "test"},
        "timing_scope": "message",
        "provider": "fake",
        "passed": True,
        "error_rate": 0,
        "code_version": "same",
        "p50_ms": 10,
        "p95_ms": 20,
        "mean_database_queries": 5,
        "mean_database_ms": 3,
    }
    candidate = {**baseline, "p50_ms": 5}
    if failure == "environment":
        candidate["environment"] = {"system": "different"}
    elif failure == "missing_version":
        candidate["versions"] = {}
    else:
        candidate["passed"] = False
        candidate["error_rate"] = 0.5
    report = compare(baseline, candidate, candidate)
    assert all(row["candidate_change_percent"] is None for row in report["rows"])
    assert report["retained"] is None
