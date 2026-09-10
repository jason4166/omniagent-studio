import json
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest

from omniagent.telemetry import Telemetry, correlation, span

pytestmark = pytest.mark.unit


def test_concurrent_traces_are_isolated_and_error_spans_close_without_payloads():
    telemetry = Telemetry()
    barrier = Barrier(2)

    def request(identifier):
        with telemetry.activate(request_id=identifier), span("api"):
            barrier.wait(timeout=5)
            try:
                with correlation(run_id=identifier + "-run"), span("llm", prompt="private input"):
                    raise ValueError("secret payload that must not be logged")
            except ValueError:
                pass

    with ThreadPoolExecutor(max_workers=2) as executor:
        list(executor.map(request, ["one", "two"]))
    records = telemetry.local.snapshot()
    assert len(records) == 4
    for identifier in ["one", "two"]:
        group = [r for r in records if r["attributes"]["request_id"] == identifier]
        assert len({r["trace_id"] for r in group}) == 1
        assert next(r for r in group if r["name"] == "llm")["status"] == "error"
    assert len({r["trace_id"] for r in records}) == 2
    assert "private input" not in json.dumps(records)
    assert "secret payload" not in json.dumps(records)
    with span("outside"):
        pass
    assert len(telemetry.local.snapshot()) == 4
    telemetry.shutdown()
