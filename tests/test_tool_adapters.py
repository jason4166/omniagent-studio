import pytest

from omniagent.profiles import AgentProfile
from omniagent.tool_adapters import (
    SYNTHETIC_PRODUCTS,
    SYNTHETIC_WARRANTIES,
    CalculatorAdapter,
    CheckWarrantyAdapter,
    LookupProductAdapter,
    ProductNotFoundError,
)
from omniagent.tool_registry import ToolRegistry
from omniagent.tooling import BudgetPolicy, ToolCall, ToolDefinition, ToolRisk


def test_calculator_adapter_translates_arguments_and_result() -> None:
    adapter = CalculatorAdapter()

    result = adapter.execute({"expression": "(1 + 2) * 3"})

    assert result == {"value": 9}


def test_calculator_adapter_runs_through_registry() -> None:
    registry = ToolRegistry()
    registry.register(
        ToolDefinition(
            name="calculator",
            risk=ToolRisk.LOW,
            parameters_schema={
                "type": "object",
                "properties": {
                    "expression": {"type": "string"},
                },
                "required": ["expression"],
                "additionalProperties": False,
            },
            allowed_roles=("sales_member",),
            requires_approval=False,
        ),
        CalculatorAdapter(),
    )
    call = ToolCall(
        call_id="call-calculator-001",
        tool_name="calculator",
        arguments={"expression": "(1 + 2) * 3"},
        profile_id="sales",
        thread_id="thread-001",
    )
    profile = AgentProfile(
        profile_id="sales",
        tool_ids=["calculator"],
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

    assert result.status == "succeeded"
    assert result.data == {"value": 9}
    assert result.error is None


def test_lookup_product_adapter_returns_copy_without_mutating_source() -> None:
    adapter = LookupProductAdapter()
    original_product = SYNTHETIC_PRODUCTS["DEMO-100"].copy()

    first_result = adapter.execute({"sku": "DEMO-100"})
    second_result = adapter.execute({"sku": "DEMO-100"})

    assert first_result == original_product
    assert second_result == original_product
    assert first_result is not SYNTHETIC_PRODUCTS["DEMO-100"]
    assert second_result is not SYNTHETIC_PRODUCTS["DEMO-100"]
    assert SYNTHETIC_PRODUCTS["DEMO-100"] == original_product


def test_lookup_product_adapter_raises_business_error_for_missing_sku() -> None:
    adapter = LookupProductAdapter()

    with pytest.raises(ProductNotFoundError) as exc_info:
        adapter.execute({"sku": "MISSING-404"})

    assert exc_info.value.code == "product_not_found"
    assert exc_info.value.message == "Product was not found"


def test_registry_maps_product_not_found_to_structured_failure() -> None:
    registry = ToolRegistry()
    registry.register(
        ToolDefinition(
            name="lookup_product",
            risk=ToolRisk.LOW,
            parameters_schema={
                "type": "object",
                "properties": {
                    "sku": {"type": "string"},
                },
                "required": ["sku"],
                "additionalProperties": False,
            },
            allowed_roles=("sales_member",),
            requires_approval=False,
        ),
        LookupProductAdapter(),
    )
    call = ToolCall(
        call_id="call-product-missing-001",
        tool_name="lookup_product",
        arguments={"sku": "MISSING-404"},
        profile_id="sales",
        thread_id="thread-001",
    )
    profile = AgentProfile(
        profile_id="sales",
        tool_ids=["lookup_product"],
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

    assert result.status == "failed"
    assert result.data is None
    assert result.error is not None
    assert result.error.code == "product_not_found"
    assert result.error.message == "Product was not found"


def test_check_warranty_adapter_returns_copy_without_mutating_source() -> None:

    adapter = CheckWarrantyAdapter()

    original_warranty = SYNTHETIC_WARRANTIES["SERIAL-DEMO-100"].copy()

    first_result = adapter.execute({"serial_number": "SERIAL-DEMO-100"})
    second_result = adapter.execute({"serial_number": "SERIAL-DEMO-100"})

    assert first_result == original_warranty
    assert second_result == original_warranty

    assert first_result is not SYNTHETIC_WARRANTIES["SERIAL-DEMO-100"]
    assert second_result is not SYNTHETIC_WARRANTIES["SERIAL-DEMO-100"]
    assert SYNTHETIC_WARRANTIES["SERIAL-DEMO-100"] == original_warranty
