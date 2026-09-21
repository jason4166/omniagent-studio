import pytest
from pydantic import ValidationError

from omniagent.demo_data import business_schemas
from omniagent.llm import RouteDecision
from omniagent.tool_clarification import argument_clarification, parameter_constraints

pytestmark = pytest.mark.unit


@pytest.mark.parametrize("route", ["tool", "clarify"])
def test_tool_intent_can_preserve_invalid_business_values_for_server_validation(route):
    decision = RouteDecision(
        route=route,
        reason="User supplied a percentage",
        confidence=1,
        tool_name="arbitrary_registered_tool",
        args={"percent": 30},
    )
    assert decision.args == {"percent": 30}


@pytest.mark.parametrize("route", ["direct", "retrieve"])
def test_other_routes_cannot_smuggle_tool_arguments(route):
    with pytest.raises(ValidationError):
        RouteDecision(route=route, reason="invalid", confidence=1, tool_name="write", args={})


def test_partial_tool_clarification_requires_a_named_intent():
    with pytest.raises(ValidationError):
        RouteDecision(route="clarify", reason="invalid", confidence=1, args={"percent": 30})
    decision = RouteDecision(route="clarify", reason="missing", confidence=1, tool_name="write")
    assert decision.args is None
    intent = RouteDecision(route="tool", reason="missing", confidence=1, tool_name="write")
    assert intent.args == {}


def test_missing_fields_include_numeric_limits_from_the_authorized_schema():
    output = argument_clarification(business_schemas()["request_discount"], {})
    assert output is not None
    assert "客户编号" in output and "申请原因" in output and "申请折扣（%）" in output
    assert "整数，范围 1 到 20（含边界）" in output
    assert "最多 500 个字符" in output
    assert "customer_id" not in output and "percent" not in output
    assert "文本" not in output and "至少 1 个字符" not in output
    assert "创建审批" not in output


def test_bounds_are_schema_driven_and_do_not_echo_or_coerce_the_invalid_input():
    schema = {
        "type": "object",
        "properties": {
            "quantity": {"title": "件数", "type": "integer", "minimum": 2, "maximum": 7}
        },
        "required": ["quantity"],
        "additionalProperties": False,
    }
    arguments = {"quantity": "secret=synthetic-private-value"}
    output = argument_clarification(schema, arguments)
    assert output is not None and "件数：整数，范围 2 到 7" in output
    assert "secret" not in output and "synthetic-private-value" not in output
    assert arguments == {"quantity": "secret=synthetic-private-value"}
    assert argument_clarification(schema, {"quantity": 7}) is None
    assert argument_clarification(schema, {"quantity": 7, "extra": "private"}) is not None


def test_enum_and_exclusive_bounds_are_not_replaced_by_invented_business_rules():
    assert "小于 10" in parameter_constraints({"type": "number", "exclusiveMaximum": 10})
    assert '可选值：["甲", "乙"]' in parameter_constraints({"type": "string", "enum": ["甲", "乙"]})
