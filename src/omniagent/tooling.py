from enum import Enum
from typing import Literal, Self
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

STRICT_NO_ARGUMENTS_SCHEMA: dict[str, object] = {
    "type": "object",
    "properties": {},
    "additionalProperties": False,
}


def build_strict_no_arguments_schema() -> dict[str, object]:
    return STRICT_NO_ARGUMENTS_SCHEMA.copy()


class ToolRisk(Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class ToolConfigurationError(ValueError):
    pass


class ToolBusinessError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class BudgetPolicy(BaseModel):
    budget_policy_id: str = "standard"
    max_calls: int = Field(gt=0, le=100)


class ApprovalPolicy(BaseModel):
    approval_policy_id: str
    require_high_risk: bool = True
    require_write: bool = True


class ToolDefinition(BaseModel):
    name: str
    risk: ToolRisk
    parameters_schema: dict[str, object] = Field(default_factory=build_strict_no_arguments_schema)
    allowed_roles: tuple[str, ...] = ()
    tags: list[str] = Field(default_factory=list)
    requires_approval: bool = True

    @model_validator(mode="after")
    def validate_approval(self) -> Self:
        if self.risk is ToolRisk.HIGH and not self.requires_approval:
            raise ValueError("high-risk tools require approval")
        return self

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        cleaned = value.strip()
        if cleaned == "":
            raise ValueError("tool name must not be blank")
        return cleaned

    def add_tag(self, raw_tag: str) -> None:
        tag = raw_tag.strip()
        if tag == "":
            raise ValueError("tag must not be blank")
        if tag not in self.tags:
            self.tags.append(tag)


class ToolCall(BaseModel):
    model_config = ConfigDict(extra="forbid")

    call_id: str
    tool_name: str
    arguments: dict[str, object]
    profile_id: str
    thread_id: str


class ToolError(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str
    message: str


class ToolResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    call_id: str
    status: Literal["succeeded", "rejected", "failed"]
    data: object | None
    error: ToolError | None
    duration_ms: float

    @model_validator(mode="after")
    def validate_state(self) -> Self:
        if self.status == "succeeded" and self.error is not None:
            raise ValueError("succeeded result must not contain error")
        return self


def generate_call_id() -> str:
    return f"call-{uuid4()}"


def parse_tool_risk(raw: str) -> ToolRisk:
    try:
        return ToolRisk(raw)
    except ValueError as exc:
        raise ToolConfigurationError(f"unknown tool risk: {raw}") from exc
