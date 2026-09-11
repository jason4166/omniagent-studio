from pathlib import Path
from unittest.mock import Mock

import pytest
from pydantic import ValidationError

from omniagent.application import ProfileBundle
from omniagent.connectors import catalog
from omniagent.errors import ErrorCode, PlatformError
from omniagent.preflight import validate_preflight_configuration
from omniagent.profiles import AgentProfile
from omniagent.tool_registry import ToolRegistry
from omniagent.tooling import ToolRisk

pytestmark = pytest.mark.unit


def preset():
    path = Path(__file__).resolve().parents[1] / "presets/workflows/sales-preflight-v1.json"
    bundle = ProfileBundle.model_validate_json(path.read_text(encoding="utf-8"))
    registry = ToolRegistry()
    definitions, _ = catalog("127.0.0.1", 18081)
    for definition in definitions:
        registry.register(definition, Mock())
    return bundle.profile, registry


def test_versioned_workflow_preset_is_importable_with_existing_tools():
    profile, registry = preset()
    validate_preflight_configuration(profile, registry)
    assert profile.profile_id == "sales-preflight-v1"
    legacy = AgentProfile.model_validate(
        {key: value for key, value in profile.model_dump().items() if key != "write_preflight"}
    )
    assert legacy.write_preflight is None


@pytest.mark.parametrize("change", ["risk", "effect", "approval", "mapping", "auto_approve"])
def test_preflight_configuration_requires_a_fixed_low_risk_read_with_valid_bindings(change):
    profile, registry = preset()
    read = registry.definition(profile.write_preflight.read_tool)
    if change == "mapping":
        profile.write_preflight = profile.write_preflight.model_copy(
            update={"argument_map": {"customer_id": "unrecognized_field"}}
        )
    elif change == "auto_approve":
        profile.auto_approve_read = False
    else:
        mutation = {
            "risk": {"risk": ToolRisk.MEDIUM},
            "effect": {"effect": "write"},
            "approval": {"requires_approval": True},
        }[change]
        registry.register(read.model_copy(update=mutation), Mock())
    with pytest.raises(PlatformError) as failure:
        validate_preflight_configuration(profile, registry)
    assert failure.value.code == ErrorCode.VALIDATION


@pytest.mark.parametrize("change", ["missing_read", "missing_policy", "same_tool"])
def test_preflight_profile_cannot_escape_its_own_tool_or_knowledge_scope(change):
    profile, _ = preset()
    data = profile.model_dump()
    if change == "missing_read":
        data["tool_ids"].remove("lookup_customer")
    elif change == "missing_policy":
        data["knowledge_base_ids"] = []
    else:
        data["write_preflight"]["read_tool"] = "request_discount"
    with pytest.raises(ValidationError):
        AgentProfile.model_validate(data)
