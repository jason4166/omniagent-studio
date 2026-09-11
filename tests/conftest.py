"""Legacy isolated tests inherit the unit layer; explicit markers keep their layers."""

import os
from pathlib import Path

import pytest

# Legacy offline contracts explicitly opt into test-only identities. Serving defaults to passwords.
os.environ["OMNIAGENT_ENV"] = "test"
os.environ["OMNIAGENT_AUTH_MODE"] = "dev"
if reference := os.environ.pop("OMNIAGENT_DATABASE_URL_FILE", None):
    os.environ["OMNIAGENT_DATABASE_URL"] = Path(reference).read_text(encoding="utf-8").strip()
    os.environ["OMNIAGENT_TEST_DATABASE_URL"] = os.environ["OMNIAGENT_DATABASE_URL"]


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    layers = {"unit", "contract", "integration", "e2e", "eval", "security"}
    for item in items:
        if not any(marker.name in layers for marker in item.iter_markers()):
            item.add_marker(pytest.mark.unit)
