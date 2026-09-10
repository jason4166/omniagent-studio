"""Resource budget interfaces; monetary accounting is not implemented yet."""

from pydantic import BaseModel, ConfigDict, Field

from omniagent.llm import LLMUsage


class ResourceBudget(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    max_total_tokens: int | None = Field(default=None, ge=0, strict=True)
    max_cost_microusd: int | None = Field(default=None, ge=0, strict=True)

    @property
    def requires_enforcement(self) -> bool:
        return self.max_total_tokens is not None or self.max_cost_microusd is not None


def accumulate_reported_tokens(previous: int | None, usage: LLMUsage | None) -> int | None:
    if previous is None or usage is None:
        return None
    if usage.total_tokens != usage.input_tokens + usage.output_tokens:
        return None
    return previous + usage.total_tokens
