from typing import Annotated, Self

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    ValidationInfo,
    field_validator,
    model_validator,
)

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

    knowledge_base_id: str = Field(min_length=1, max_length=120)
    name: str = Field(min_length=1, max_length=160)

    @field_validator("knowledge_base_id", "name")
    @classmethod
    def validate_non_blank(cls, value: str) -> str:
        cleaned = value.strip()
        if cleaned == "":
            raise ValueError("value must not be blank")
        return cleaned


ArgumentName = Annotated[str, Field(pattern=r"^[a-zA-Z_][a-zA-Z0-9_]{0,63}$")]


class WritePreflightConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)
    write_tool: str = Field(min_length=1, max_length=120)
    read_tool: str = Field(min_length=1, max_length=120)
    argument_map: dict[ArgumentName, ArgumentName] = Field(min_length=1, max_length=8)
    policy_query: str = Field(min_length=1, max_length=500)


class AgentProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(default="Agent", min_length=1, max_length=120)
    description: str = Field(default="", max_length=1000)
    provider_id: str = Field(default="fake", max_length=120)
    model: str = Field(default="fake-v1", max_length=120)
    temperature: float = Field(default=0, ge=0, le=2)
    allowed_roles: tuple[str, ...] = ("admin", "member", "viewer")
    auto_approve_read: bool = True
    require_evidence: bool = True
    context_policy: ContextPolicy = Field(default_factory=ContextPolicy)
    budgets: RunBudget = Field(default_factory=RunBudget)
    write_preflight: WritePreflightConfig | None = None

    profile_id: str
    version: int = Field(default=1, ge=1)
    enabled: bool = True
    tool_ids: list[str] = Field(default_factory=list)
    knowledge_base_ids: list[str] = Field(default_factory=list)
    prompt_version_id: str
    budget_policy_id: str
    approval_policy_id: str

    @model_validator(mode="after")
    def validate_preflight_references(self) -> Self:
        configuration = self.write_preflight
        if configuration is not None and (
            configuration.write_tool == configuration.read_tool
            or configuration.write_tool not in self.tool_ids
            or configuration.read_tool not in self.tool_ids
            or not self.knowledge_base_ids
        ):
            raise ValueError(
                "Write preflight requires distinct authorized tools and a knowledge base"
            )
        return self

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
        if cleaned == "" or len(cleaned) > 120:
            raise ValueError(f"{info.field_name} must not be blank")
        return cleaned

    @field_validator("tool_ids", "knowledge_base_ids")
    @classmethod
    def validate_unique_ids(
        cls,
        value: list[str],
        info: ValidationInfo,
    ) -> list[str]:
        if len(value) > 64 or any(not item.strip() or len(item) > 120 for item in value):
            raise ValueError(f"{info.field_name} must contain bounded nonblank identifiers")
        if len(value) != len(set(value)):
            raise ValueError(f"{info.field_name} must be unique")
        return value


class AgentProfilePatch(BaseModel):
    expected_version: int = Field(ge=1)
    tool_ids: list[str] = Field(default_factory=list)
