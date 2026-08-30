import pytest

from omniagent.profiles import AgentProfile
from omniagent.tool_catalog import build_default_tool_registry
from omniagent.tooling import BudgetPolicy, ToolCall


@pytest.mark.parametrize(
    (
        "tool_name",
        "arguments",
        "expected_status",
        "expected_data",
        "expected_error_code",
    ),
    [
        (
            "calculator",
            {"expression": "1 + 2"},
            "succeeded",
            {"value": 3},
            None,
        ),
        (
            "lookup_product",
            {"sku": "DEMO-100"},
            "succeeded",
            {
                "sku": "DEMO-100",
                "name": "Synthetic Keyboard",
                "available": True,
            },
            None,
        ),
        (
            "check_warranty",
            {"serial_number": "SERIAL-DEMO-100"},
            "succeeded",
            {
                "serial_number": "SERIAL-DEMO-100",
                "status": "active",
                "expires_on": "2030-12-31",
            },
            None,
        ),
        (
            "create_followup",
            {
                "customer_id": "CUSTOMER-DEMO-100",
                "note": "Synthetic follow-up note",
            },
            "rejected",
            None,
            "approval_required",
        ),
    ],
)
def test_default_registry_routes_all_four_tools(
    tool_name: str,
    arguments: dict[str, object],
    expected_status: str,
    expected_data: object,
    expected_error_code: str | None,
) -> None:
    registry = build_default_tool_registry()
    call = ToolCall(
        call_id=f"call-{tool_name}-001",
        tool_name=tool_name,
        arguments=arguments,
        profile_id="sales",
        thread_id="thread-001",
    )
    profile = AgentProfile(
        profile_id="sales",
        tool_ids=[tool_name],
        prompt_version_id="sales:v1",
        budget_policy_id="standard",
        approval_policy_id="safe-default",
    )

    result = registry.execute(
        call,
        profile,
        actor_role="sales_member",
        approval_granted=False,
        budget_policy=BudgetPolicy(max_calls=3),
        calls_used=0,
    )

    assert result.status == expected_status
    assert result.data == expected_data
    if expected_error_code is None:
        assert result.error is None
    else:
        assert result.error is not None
        assert result.error.code == expected_error_code
