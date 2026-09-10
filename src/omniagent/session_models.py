"""Bounded JSON domain state; clients and credentials are runtime dependencies."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from omniagent.context import HistoryMessage


class RunBudget(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    max_steps: int = Field(default=24, ge=2, le=100)
    max_model_calls: int = Field(default=4, ge=1, le=12)
    max_tool_calls: int = Field(default=4, ge=0, le=20)
    max_tokens: int = Field(default=64000, ge=512, le=256000)
    max_cost_microusd: int | None = Field(default=None, ge=0)
    deadline_seconds: int = Field(default=120, ge=5, le=300)


class Usage(BaseModel):
    steps: int = 0
    model_calls: int = 0
    retrieval_calls: int = 0
    tool_calls: int = 0
    reserved_tokens: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    cost_microusd: int | None = None


class SessionData(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal[1] = 1
    thread_id: str
    user_id: str
    profile_id: str
    profile_version: int
    status: Literal["ready", "running", "awaiting_approval", "completed", "failed", "cancelled"]
    run_id: str | None = None
    request_key: str | None = None
    request_hash: str | None = None
    message: str = ""
    history: list[HistoryMessage] = Field(default_factory=list)
    usage: Usage = Field(default_factory=Usage)
    deadline_at: float = 0
    remaining_seconds: float = 0
    approval_id: str | None = None
    result: dict[str, object] | None = None
    error: str | None = None


class ApprovalDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: Literal["approve", "edit", "reject"]
    expected_version: int = Field(ge=1)
    decision_key: str = Field(min_length=8, max_length=128, pattern=r"^[a-zA-Z0-9_-]+$")
    arguments: dict[str, object] | None = None
