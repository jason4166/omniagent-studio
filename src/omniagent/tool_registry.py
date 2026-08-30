import json
from dataclasses import dataclass
from time import perf_counter
from typing import Protocol

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError
from jsonschema.exceptions import ValidationError as JsonSchemaValidationError

from omniagent.profiles import AgentProfile
from omniagent.tooling import (
    BudgetPolicy,
    ToolBusinessError,
    ToolCall,
    ToolDefinition,
    ToolError,
    ToolResult,
)


class ToolSchemaError(ValueError):
    pass


class ToolAdapter(Protocol):
    def execute(self, arguments: dict[str, object]) -> object: ...


@dataclass(frozen=True)
class RegisteredTool:
    definition: ToolDefinition
    adapter: ToolAdapter


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, RegisteredTool] = {}

    def register(self, definition: ToolDefinition, adapter: ToolAdapter) -> None:
        try:
            Draft202012Validator.check_schema(definition.parameters_schema)
        except SchemaError as exc:
            raise ToolSchemaError("invalid tool parameters schema") from exc
        self._tools[definition.name] = RegisteredTool(
            definition=definition,
            adapter=adapter,
        )

    def execute(
        self,
        call: ToolCall,
        profile: AgentProfile,
        actor_role: str,
        approval_granted: bool,
        budget_policy: BudgetPolicy,
        calls_used: int,
    ) -> ToolResult:
        started_at = perf_counter()
        registered_tool = self._tools.get(call.tool_name)

        if registered_tool is None:
            return ToolResult(
                call_id=call.call_id,
                status="rejected",
                data=None,
                error=ToolError(
                    code="unknown_tool",
                    message="Tool is not registered",
                ),
                duration_ms=(perf_counter() - started_at) * 1_000,
            )
        if call.profile_id != profile.profile_id:
            return ToolResult(
                call_id=call.call_id,
                status="rejected",
                data=None,
                error=ToolError(
                    code="profile_mismatch",
                    message=("Tool call profile does not match the execution profile"),
                ),
                duration_ms=(perf_counter() - started_at) * 1_000,
            )
        if call.tool_name not in profile.tool_ids:
            return ToolResult(
                call_id=call.call_id,
                status="rejected",
                data=None,
                error=ToolError(
                    code="tool_not_allowed",
                    message=("Tool is not allowed for this profile"),
                ),
                duration_ms=(perf_counter() - started_at) * 1_000,
            )
        if actor_role not in registered_tool.definition.allowed_roles:
            return ToolResult(
                call_id=call.call_id,
                status="rejected",
                data=None,
                error=ToolError(
                    code="role_not_allowed",
                    message="Actor role is not allowed for this tool",
                ),
                duration_ms=(perf_counter() - started_at) * 1_000,
            )
        validator = Draft202012Validator(registered_tool.definition.parameters_schema)
        try:
            validator.validate(call.arguments)
        except JsonSchemaValidationError:
            return ToolResult(
                call_id=call.call_id,
                status="rejected",
                data=None,
                error=ToolError(
                    code="invalid_arguments",
                    message="Tool arguments failed schema validation",
                ),
                duration_ms=(perf_counter() - started_at) * 1_000,
            )
        if registered_tool.definition.requires_approval and not approval_granted:
            return ToolResult(
                call_id=call.call_id,
                status="rejected",
                data=None,
                error=ToolError(
                    code="approval_required",
                    message="Tool execution requires approval",
                ),
                duration_ms=(perf_counter() - started_at) * 1_000,
            )

        if calls_used >= budget_policy.max_calls:
            return ToolResult(
                call_id=call.call_id,
                status="rejected",
                data=None,
                error=ToolError(
                    code="budget_exceeded",
                    message="Tool call budget is exhausted",
                ),
                duration_ms=(perf_counter() - started_at) * 1_000,
            )

        try:
            adapter_data = registered_tool.adapter.execute(call.arguments)
        except ToolBusinessError as exc:
            return ToolResult(
                call_id=call.call_id,
                status="failed",
                data=None,
                error=ToolError(
                    code=exc.code,
                    message=exc.message,
                ),
                duration_ms=(perf_counter() - started_at) * 1_000,
            )

        except TimeoutError:
            return ToolResult(
                call_id=call.call_id,
                status="failed",
                data=None,
                error=ToolError(
                    code="tool_timeout",
                    message="Tool execution timed out",
                ),
                duration_ms=(perf_counter() - started_at) * 1_000,
            )
        except Exception:
            return ToolResult(
                call_id=call.call_id,
                status="failed",
                data=None,
                error=ToolError(
                    code="tool_execution_failed",
                    message="Tool execution failed",
                ),
                duration_ms=(perf_counter() - started_at) * 1_000,
            )

        try:
            json.dumps(adapter_data, allow_nan=False)
        except (TypeError, ValueError):
            return ToolResult(
                call_id=call.call_id,
                status="failed",
                data=None,
                error=ToolError(
                    code="non_serializable_result",
                    message="Tool result is not JSON serializable",
                ),
                duration_ms=(perf_counter() - started_at) * 1_000,
            )

        return ToolResult(
            call_id=call.call_id,
            status="succeeded",
            data=adapter_data,
            error=None,
            duration_ms=(perf_counter() - started_at) * 1_000,
        )
