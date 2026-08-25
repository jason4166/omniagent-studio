import pytest
from pydantic import ValidationError

from omniagent.tooling import (
    BudgetPolicy,
    ToolConfigurationError,
    ToolDefinition,
    ToolRisk,
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
