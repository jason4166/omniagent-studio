import json

import pytest

from omniagent.connectors import catalog
from omniagent.profiles import AgentProfile
from omniagent.runtime_instructions import route_instruction
from omniagent.tool_registry import ToolRegistry
from omniagent.tooling import ToolDefinition, ToolRisk

pytestmark = pytest.mark.unit


class NoExecution:
    def execute(self, arguments: dict[str, object]) -> object:
        pytest.fail("Constructing routing instructions cannot execute a tool")


def profile_with_tools(*names: str) -> AgentProfile:
    return AgentProfile(
        profile_id="configured-team",
        prompt_version_id="routing:v1",
        budget_policy_id="standard",
        approval_policy_id="safe-default",
        tool_ids=list(names),
    )


def test_route_contract_uses_parameter_business_labels_without_changing_schema() -> None:
    definitions, _ = catalog("127.0.0.1", 8001)
    registry = ToolRegistry()
    for definition in definitions:
        registry.register(definition, NoExecution())
    original = next(item for item in definitions if item.name == "create_followup")

    instruction = route_instruction(profile_with_tools("create_followup"), registry)
    contracts = json.loads(instruction.split("Authorized tools: ", 1)[1])

    assert len(contracts) == 1
    assert contracts[0]["name"] == "create_followup"
    assert contracts[0]["parameter_labels"] == {"customer_id": "客户编号", "note": "备注"}
    assert contracts[0]["parameters"] == original.parameters_schema
    assert contracts[0]["parameters"]["required"] == ["customer_id", "note"]
    assert "names in output_text, including parenthetical names" in instruction
    assert "JSON args keys MUST remain exactly as defined in parameters" in instruction
    assert "Copy user-provided identifiers, free-text notes and reasons verbatim into args" in (
        instruction
    )
    assert "original language, spelling, case, punctuation and whitespace" in instruction


def test_route_parameter_labels_follow_tool_profile_and_enabled_allowlists() -> None:
    registry = ToolRegistry()
    for name, property_name, enabled in (
        ("allowed", "customer_id", True),
        ("another-profile", "sku", True),
        ("disabled", "serial_number", False),
    ):
        registry.register(
            ToolDefinition(
                name=name,
                risk=ToolRisk.LOW,
                enabled=enabled,
                parameters_schema={
                    "type": "object",
                    "properties": {property_name: {"type": "string"}},
                },
            ),
            NoExecution(),
        )

    instruction = route_instruction(profile_with_tools("allowed", "disabled"), registry)
    contracts = json.loads(instruction.split("Authorized tools: ", 1)[1])

    assert [item["name"] for item in contracts] == ["allowed"]
    assert contracts[0]["parameter_labels"] == {"customer_id": "客户编号"}
    for excluded in (
        "another-profile",
        "disabled",
        "sku",
        "serial_number",
        "产品编号",
        "设备序列号",
    ):
        assert excluded not in instruction


@pytest.mark.parametrize(
    ("schema", "labels"),
    [
        ({"type": "object"}, {}),
        (
            {
                "type": "object",
                "properties": {"currency": {"type": "string"}, "custom_field": {"type": "string"}},
            },
            {"currency": "币种"},
        ),
    ],
)
def test_route_labels_include_only_known_actual_properties(
    schema: dict[str, object], labels: dict[str, str]
) -> None:
    registry = ToolRegistry()
    registry.register(
        ToolDefinition(name="custom", risk=ToolRisk.LOW, parameters_schema=schema), NoExecution()
    )

    instruction = route_instruction(profile_with_tools("custom"), registry)
    contract = json.loads(instruction.split("Authorized tools: ", 1)[1])[0]

    assert contract["parameter_labels"] == labels
    assert contract["parameters"] == schema
    assert "CNY" not in instruction
    assert "customer_id" not in instruction
