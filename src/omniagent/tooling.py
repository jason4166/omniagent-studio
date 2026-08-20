from dataclasses import dataclass, field
from enum import Enum


class ToolRisk(Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class ToolConfigurationError(ValueError):
    pass


@dataclass
class BudgetPolicy:
    max_calls: int

    def __post_init__(self) -> None:
        if self.max_calls <= 0:
            raise ValueError("max_calls must be greater than 0")


@dataclass
class ToolDefinition:
    name: str
    risk: ToolRisk
    tags: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.name.strip() == "":
            raise ValueError("tool name must not be blank")

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
