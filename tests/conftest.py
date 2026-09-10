"""Legacy isolated tests inherit the unit layer; explicit markers keep their layers."""

import pytest


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    layers = {"unit", "contract", "integration", "e2e", "eval", "security"}
    for item in items:
        if not any(marker.name in layers for marker in item.iter_markers()):
            item.add_marker(pytest.mark.unit)
