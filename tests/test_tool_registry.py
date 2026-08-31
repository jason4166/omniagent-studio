import pytest

from omniagent.profiles import AgentProfile
from omniagent.tool_registry import ToolRegistry, ToolSchemaError
from omniagent.tooling import BudgetPolicy, ToolCall, ToolDefinition, ToolRisk


class RecordingAdapter:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def execute(self, arguments: dict[str, object]) -> object:
        self.calls.append(arguments)
        return {"ok": True}


class TimeoutAdapter:
    def execute(self, arguments: dict[str, object]) -> object:
        raise TimeoutError("synthetic upstream timeout")


class NonSerializableAdapter:
    def execute(self, arguments: dict[str, object]) -> object:
        return {"matched_ids": {"A-1", "A-2"}}


class UnexpectedFailureAdapter:
    def execute(self, arguments: dict[str, object]) -> object:
        raise RuntimeError("synthetic private failure detail")


def make_profile(*tool_ids: str) -> AgentProfile:
    return AgentProfile(
        profile_id="sales",
        tool_ids=list(tool_ids),
        prompt_version_id="sales:v1",
        budget_policy_id="standard",
        approval_policy_id="safe-default",
    )


def make_budget_policy(max_calls: int = 3) -> BudgetPolicy:
    return BudgetPolicy(max_calls=max_calls)


def test_registry_reports_whether_tool_is_registered() -> None:
    registry = ToolRegistry()
    registry.register(
        ToolDefinition(
            name="known_tool",
            risk=ToolRisk.LOW,
            requires_approval=False,
        ),
        RecordingAdapter(),
    )

    assert registry.has("known_tool") is True
    assert registry.has("missing_tool") is False


def test_unknown_tool_is_rejected_before_adapter() -> None:
    registry = ToolRegistry()
    adapter = RecordingAdapter()
    registry.register(
        ToolDefinition(
            name="known_tool",
            risk=ToolRisk.LOW,
            requires_approval=False,
        ),
        adapter,
    )
    call = ToolCall(
        call_id="call-unknown-001",
        tool_name="missing_tool",
        arguments={},
        profile_id="sales",
        thread_id="thread-001",
    )

    result = registry.execute(
        call,
        make_profile(),
        actor_role="sales_member",
        approval_granted=False,
        budget_policy=make_budget_policy(),
        calls_used=0,
    )

    assert result.call_id == call.call_id
    assert result.status == "rejected"
    assert result.error is not None
    assert result.error.code == "unknown_tool"
    assert result.duration_ms >= 0
    assert adapter.calls == []


def test_register_rejects_invalid_parameters_schema() -> None:
    registry = ToolRegistry()
    adapter = RecordingAdapter()
    definition = ToolDefinition(
        name="bad_schema_tool",
        risk=ToolRisk.LOW,
        parameters_schema={
            "type": "object",
            "properties": {
                "sku": {"type": "strng"},
            },
        },
        requires_approval=False,
    )

    with pytest.raises(
        ToolSchemaError,
        match="invalid tool parameters schema",
    ):
        registry.register(definition, adapter)

    assert adapter.calls == []


@pytest.mark.parametrize(
    "invalid_arguments",
    [
        {},
        {"sku": 100},
        {"sku": "DEMO-100", "debug": True},
    ],
)
def test_invalid_arguments_are_rejected_before_adapter(
    invalid_arguments: dict[str, object],
) -> None:
    registry = ToolRegistry()
    adapter = RecordingAdapter()
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
        adapter,
    )
    call = ToolCall(
        call_id="call-invalid-arguments-001",
        tool_name="lookup_product",
        arguments=invalid_arguments,
        profile_id="sales",
        thread_id="thread-001",
    )

    result = registry.execute(
        call,
        make_profile("lookup_product"),
        actor_role="sales_member",
        approval_granted=False,
        budget_policy=make_budget_policy(),
        calls_used=0,
    )

    assert result.call_id == call.call_id
    assert result.status == "rejected"
    assert result.error is not None
    assert result.error.code == "invalid_arguments"
    assert adapter.calls == []


def test_profile_disallowed_tool_is_rejected_before_adapter() -> None:
    registry = ToolRegistry()
    adapter = RecordingAdapter()
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
            requires_approval=False,
        ),
        adapter,
    )
    call = ToolCall(
        call_id="call-profile-denied-001",
        tool_name="lookup_product",
        arguments={"sku": "DEMO-100"},
        profile_id="sales",
        thread_id="thread-001",
    )

    result = registry.execute(
        call,
        make_profile(),
        actor_role="sales_member",
        approval_granted=False,
        budget_policy=make_budget_policy(),
        calls_used=0,
    )

    assert result.status == "rejected"
    assert result.error is not None
    assert result.error.code == "tool_not_allowed"
    assert adapter.calls == []


def test_profile_mismatch_is_rejected_before_adapter() -> None:
    registry = ToolRegistry()
    adapter = RecordingAdapter()
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
            requires_approval=False,
        ),
        adapter,
    )
    call = ToolCall(
        call_id="call-profile-mismatch-001",
        tool_name="lookup_product",
        arguments={"sku": "DEMO-100"},
        profile_id="sales",
        thread_id="thread-001",
    )
    admin_profile = AgentProfile(
        profile_id="admin",
        tool_ids=["lookup_product"],
        prompt_version_id="admin:v1",
        budget_policy_id="standard",
        approval_policy_id="safe-default",
    )

    result = registry.execute(
        call,
        admin_profile,
        actor_role="sales_member",
        approval_granted=False,
        budget_policy=make_budget_policy(),
        calls_used=0,
    )

    assert result.status == "rejected"
    assert result.error is not None
    assert result.error.code == "profile_mismatch"
    assert adapter.calls == []


def test_disallowed_role_is_rejected_before_adapter() -> None:
    registry = ToolRegistry()
    adapter = RecordingAdapter()
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
            allowed_roles=("sales_manager",),
            requires_approval=False,
        ),
        adapter,
    )
    call = ToolCall(
        call_id="call-role-denied-001",
        tool_name="lookup_product",
        arguments={"sku": "DEMO-100"},
        profile_id="sales",
        thread_id="thread-001",
    )

    result = registry.execute(
        call,
        make_profile("lookup_product"),
        actor_role="sales_member",
        approval_granted=False,
        budget_policy=make_budget_policy(),
        calls_used=0,
    )

    assert result.status == "rejected"
    assert result.error is not None
    assert result.error.code == "role_not_allowed"
    assert adapter.calls == []


def test_write_tool_without_approval_is_rejected_before_adapter() -> None:
    registry = ToolRegistry()
    adapter = RecordingAdapter()
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
        adapter,
    )
    call = ToolCall(
        call_id="call-write-unapproved-001",
        tool_name="create_followup",
        arguments={
            "customer_id": "CUSTOMER-100",
            "note": "Synthetic follow-up note",
        },
        profile_id="sales",
        thread_id="thread-001",
    )

    result = registry.execute(
        call,
        make_profile("create_followup"),
        actor_role="sales_member",
        approval_granted=False,
        budget_policy=make_budget_policy(),
        calls_used=0,
    )

    assert result.status == "rejected"
    assert result.error is not None
    assert result.error.code == "approval_required"
    assert adapter.calls == []


def test_exhausted_budget_is_rejected_before_adapter() -> None:
    registry = ToolRegistry()
    adapter = RecordingAdapter()
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
        adapter,
    )
    call = ToolCall(
        call_id="call-budget-exhausted-001",
        tool_name="lookup_product",
        arguments={"sku": "DEMO-100"},
        profile_id="sales",
        thread_id="thread-001",
    )

    result = registry.execute(
        call,
        make_profile("lookup_product"),
        actor_role="sales_member",
        approval_granted=False,
        budget_policy=make_budget_policy(max_calls=3),
        calls_used=3,
    )

    assert result.status == "rejected"
    assert result.error is not None
    assert result.error.code == "budget_exceeded"
    assert adapter.calls == []


def test_allowed_read_tool_executes_adapter_and_returns_success() -> None:
    registry = ToolRegistry()
    adapter = RecordingAdapter()
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
        adapter,
    )
    arguments: dict[str, object] = {"sku": "DEMO-100"}
    call = ToolCall(
        call_id="call-read-success-001",
        tool_name="lookup_product",
        arguments=arguments,
        profile_id="sales",
        thread_id="thread-001",
    )

    result = registry.execute(
        call,
        make_profile("lookup_product"),
        actor_role="sales_member",
        approval_granted=False,
        budget_policy=make_budget_policy(max_calls=3),
        calls_used=2,
    )

    assert result.call_id == call.call_id
    assert result.status == "succeeded"
    assert result.data == {"ok": True}
    assert result.error is None
    assert result.duration_ms >= 0
    assert adapter.calls == [arguments]


def test_adapter_timeout_is_mapped_to_structured_failure() -> None:
    registry = ToolRegistry()
    registry.register(
        ToolDefinition(
            name="slow_lookup",
            risk=ToolRisk.LOW,
            allowed_roles=("sales_member",),
            requires_approval=False,
        ),
        TimeoutAdapter(),
    )
    call = ToolCall(
        call_id="call-timeout-001",
        tool_name="slow_lookup",
        arguments={},
        profile_id="sales",
        thread_id="thread-001",
    )

    result = registry.execute(
        call,
        make_profile("slow_lookup"),
        actor_role="sales_member",
        approval_granted=False,
        budget_policy=make_budget_policy(),
        calls_used=0,
    )

    assert result.status == "failed"
    assert result.data is None
    assert result.error is not None
    assert result.error.code == "tool_timeout"
    assert result.error.message == "Tool execution timed out"


def test_non_serializable_adapter_result_is_mapped_to_failure() -> None:
    registry = ToolRegistry()
    registry.register(
        ToolDefinition(
            name="invalid_result_tool",
            risk=ToolRisk.LOW,
            allowed_roles=("sales_member",),
            requires_approval=False,
        ),
        NonSerializableAdapter(),
    )
    call = ToolCall(
        call_id="call-invalid-result-001",
        tool_name="invalid_result_tool",
        arguments={},
        profile_id="sales",
        thread_id="thread-001",
    )

    result = registry.execute(
        call,
        make_profile("invalid_result_tool"),
        actor_role="sales_member",
        approval_granted=False,
        budget_policy=make_budget_policy(),
        calls_used=0,
    )

    assert result.status == "failed"
    assert result.data is None
    assert result.error is not None
    assert result.error.code == "non_serializable_result"
    assert result.error.message == "Tool result is not JSON serializable"


def test_unexpected_adapter_error_is_mapped_without_private_detail() -> None:
    registry = ToolRegistry()
    registry.register(
        ToolDefinition(
            name="unexpected_failure_tool",
            risk=ToolRisk.LOW,
            allowed_roles=("sales_member",),
            requires_approval=False,
        ),
        UnexpectedFailureAdapter(),
    )
    call = ToolCall(
        call_id="call-unexpected-failure-001",
        tool_name="unexpected_failure_tool",
        arguments={},
        profile_id="sales",
        thread_id="thread-001",
    )

    result = registry.execute(
        call,
        make_profile("unexpected_failure_tool"),
        actor_role="sales_member",
        approval_granted=False,
        budget_policy=make_budget_policy(),
        calls_used=0,
    )

    assert result.status == "failed"
    assert result.data is None
    assert result.error is not None
    assert result.error.code == "tool_execution_failed"
    assert result.error.message == "Tool execution failed"
