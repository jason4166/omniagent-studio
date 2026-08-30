from omniagent.tool_adapters import (
    CalculatorAdapter,
    CheckWarrantyAdapter,
    CreateFollowupAdapter,
    LookupProductAdapter,
)
from omniagent.tool_registry import ToolRegistry
from omniagent.tooling import ToolDefinition, ToolRisk


def build_default_tool_registry() -> ToolRegistry:
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
    registry.register(
        ToolDefinition(
            name="check_warranty",
            risk=ToolRisk.LOW,
            parameters_schema={
                "type": "object",
                "properties": {
                    "serial_number": {"type": "string"},
                },
                "required": ["serial_number"],
                "additionalProperties": False,
            },
            allowed_roles=("sales_member",),
            requires_approval=False,
        ),
        CheckWarrantyAdapter(),
    )
    registry.register(
        ToolDefinition(
            name="create_followup",
            risk=ToolRisk.MEDIUM,
            parameters_schema={
                "type": "object",
                "properties": {
                    "customer_id": {"type": "string"},
                    "note": {"type": "string"},
                },
                "required": ["customer_id", "note"],
                "additionalProperties": False,
            },
            allowed_roles=("sales_member",),
            requires_approval=True,
        ),
        CreateFollowupAdapter(),
    )
    return registry
