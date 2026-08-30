import pytest
from pydantic import ValidationError

from omniagent.tooling import (
    BudgetPolicy,
    ToolCall,
    ToolConfigurationError,
    ToolDefinition,
    ToolError,
    ToolResult,
    ToolRisk,
    generate_call_id,
    parse_tool_risk,
)


@pytest.fixture
def default_policy() -> BudgetPolicy:
    return BudgetPolicy(max_calls=3)


def test_default_policy_accepts_positive_max_calls(
    default_policy: BudgetPolicy,
) -> None:
    assert default_policy.max_calls == 3


def test_parse_tool_risk_rejects_unknown_value() -> None:
    with pytest.raises(
        ToolConfigurationError,
        match="unknown tool risk: unknown",
    ):
        parse_tool_risk("unknown")


@pytest.mark.parametrize("max_calls", [0, -1])
def test_budget_policy_rejects_invalid_max_calls(
    max_calls: int,
) -> None:
    with pytest.raises(ValidationError) as exc_info:
        BudgetPolicy(max_calls=max_calls)

    error = exc_info.value.errors()[0]
    assert error["loc"] == ("max_calls",)
    assert error["type"] == "greater_than"
    assert error["input"] == max_calls


@pytest.mark.parametrize("name", ["", "  "])
def test_tool_definition_rejects_blank_name(
    name: str,
) -> None:
    with pytest.raises(ValueError, match="tool name must not be blank"):
        ToolDefinition(
            name=name,
            risk=ToolRisk.LOW,
        )


def test_tool_definition_default_tags_are_not_shared() -> None:
    first = ToolDefinition(
        name="search",
        risk=ToolRisk.LOW,
    )
    second = ToolDefinition(
        name="email",
        risk=ToolRisk.MEDIUM,
    )

    first.tags.append("read")

    assert first.tags == ["read"]
    assert second.tags == []
    assert first.tags is not second.tags


def test_tool_definition_add_tag_strips_deduplicates_and_preserves_order() -> None:
    search = ToolDefinition(
        name="search",
        risk=ToolRisk.LOW,
    )
    search.add_tag(" read ")
    search.add_tag("read")
    search.add_tag("audit")

    assert search.tags == ["read", "audit"]


def test_tool_definition_add_tag_rejects_blank_before_mutation() -> None:
    tool = ToolDefinition(
        name="search",
        risk=ToolRisk.LOW,
    )
    tool.add_tag("read")

    with pytest.raises(
        ValueError,
        match="tag must not be blank",
    ):
        tool.add_tag("  ")

    assert tool.tags == ["read"]


def test_tool_definition_parses_external_risk_string() -> None:
    tool = ToolDefinition.model_validate(
        {
            "name": "search",
            "risk": "high",
        }
    )

    assert tool.risk is ToolRisk.HIGH


def test_tool_definition_dumps_json_compatible_values() -> None:
    tool = ToolDefinition(
        name="search",
        risk=ToolRisk.HIGH,
    )

    payload = tool.model_dump(mode="json")

    assert payload == {
        "name": "search",
        "risk": "high",
        "parameters_schema": {
            "type": "object",
            "properties": {},
            "additionalProperties": False,
        },
        "allowed_roles": [],
        "tags": [],
        "requires_approval": True,
    }


def test_tool_definition_rejects_high_risk_without_approval() -> None:
    with pytest.raises(
        ValidationError,
        match="high-risk tools require approval",
    ):
        ToolDefinition(
            name="delete_customer",
            risk=ToolRisk.HIGH,
            requires_approval=False,
        )


def test_tool_call_preserves_execution_identity_and_arguments() -> None:
    call = ToolCall(
        call_id="call-0001",
        tool_name="lookup_product",
        arguments={"sku": "DEMO-100"},
        profile_id="sales",
        thread_id="thread-001",
    )

    assert call.call_id == "call-0001"
    assert call.tool_name == "lookup_product"
    assert call.arguments == {"sku": "DEMO-100"}
    assert call.profile_id == "sales"
    assert call.thread_id == "thread-001"


def test_tool_result_represents_unknown_tool_rejection() -> None:
    result = ToolResult(
        call_id="call-0002",
        status="rejected",
        data=None,
        error=ToolError(
            code="unknown_tool",
            message="Tool is not registered",
        ),
        duration_ms=0.2,
    )

    assert result.call_id == "call-0002"
    assert result.status == "rejected"
    assert result.data is None
    assert result.error is not None
    assert result.error.code == "unknown_tool"
    assert result.duration_ms == 0.2


def test_tool_result_rejects_success_with_error() -> None:
    with pytest.raises(
        ValidationError,
        match="succeeded result must not contain error",
    ):
        ToolResult(
            call_id="call-0003",
            status="succeeded",
            data={"available": True},
            error=ToolError(
                code="unknown_tool",
                message="Tool is not registered",
            ),
            duration_ms=0.2,
        )


def test_generate_call_id_returns_distinct_prefixed_ids() -> None:
    first_call_id = generate_call_id()
    second_call_id = generate_call_id()

    assert first_call_id.startswith("call-")
    assert second_call_id.startswith("call-")
    assert first_call_id != second_call_id
