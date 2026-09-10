from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, ValidationInfo, field_validator

from omniagent.context import ContextPolicy
from omniagent.session_models import RunBudget


class PromptVersion(BaseModel):
    prompt_version_id: str
    content: str
    content_hash: str
    variables: tuple[str, ...] = ()
    created_at: AwareDatetime

    @field_validator("variables")
    @classmethod
    def validate_variables(
        cls,
        value: tuple[str, ...],
    ) -> tuple[str, ...]:
        cleaned: list[str] = []

        for variable in value:
            cleaned.append(variable.strip())

        cleaned_variables = tuple(cleaned)

        if "" in cleaned_variables:
            raise ValueError("variables must not contain blank names")

        if len(cleaned_variables) != len(set(cleaned_variables)):
            raise ValueError("variables must be unique")

        return cleaned_variables


class KnowledgeBase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    knowledge_base_id: str = Field(min_length=1)
    name: str = Field(min_length=1)

    @field_validator("knowledge_base_id", "name")
    @classmethod
    def validate_non_blank(cls, value: str) -> str:
        cleaned = value.strip()
        if cleaned == "":
            raise ValueError("value must not be blank")
        return cleaned


class AgentProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(default="Agent", min_length=1, max_length=120)
    description: str = Field(default="", max_length=1000)
    provider_id: str = "fake"
    model: str = "fake-v1"
    temperature: float = Field(default=0, ge=0, le=2)
    allowed_roles: tuple[str, ...] = ("admin", "member", "viewer")
    auto_approve_read: bool = True
    require_evidence: bool = True
    context_policy: ContextPolicy = Field(default_factory=ContextPolicy)
    budgets: RunBudget = Field(default_factory=RunBudget)

    profile_id: str
    version: int = Field(default=1, ge=1)
    enabled: bool = True
    tool_ids: list[str] = Field(default_factory=list)
    knowledge_base_ids: list[str] = Field(default_factory=list)
    prompt_version_id: str
    budget_policy_id: str
    approval_policy_id: str

    @field_validator(
        "profile_id",
        "prompt_version_id",
        "budget_policy_id",
        "approval_policy_id",
    )
    @classmethod
    def validate_required_id(
        cls,
        value: str,
        info: ValidationInfo,
    ) -> str:
        cleaned = value.strip()
        if cleaned == "":
            raise ValueError(f"{info.field_name} must not be blank")
        return cleaned

    @field_validator("tool_ids", "knowledge_base_ids")
    @classmethod
    def validate_unique_ids(
        cls,
        value: list[str],
        info: ValidationInfo,
    ) -> list[str]:
        if len(value) != len(set(value)):
            raise ValueError(f"{info.field_name} must be unique")
        return value


class AgentProfilePatch(BaseModel):
    expected_version: int = Field(ge=1)
    tool_ids: list[str] = Field(default_factory=list)
