from enum import Enum
from typing import Self

from pydantic import BaseModel, Field, field_validator, model_validator


class ToolRisk(Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class ToolConfigurationError(ValueError):
    pass


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


def parse_tool_risk(raw: str) -> ToolRisk:
    try:
        return ToolRisk(raw)
    except ValueError as exc:
        raise ToolConfigurationError(f"unknown tool risk: {raw}") from exc
