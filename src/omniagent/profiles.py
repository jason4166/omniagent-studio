from pydantic import AwareDatetime, BaseModel, Field, ValidationInfo, field_validator


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
    knowledge_base_id: str
    name: str


class AgentProfile(BaseModel):
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
