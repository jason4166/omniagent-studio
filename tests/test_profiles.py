from datetime import datetime

import pytest
from pydantic import ValidationError

from omniagent.profiles import AgentProfile, AgentProfilePatch, PromptVersion


def test_agent_profile_rejects_duplicate_tool_ids() -> None:
    with pytest.raises(
        ValidationError,
        match="tool_ids must be unique",
    ):
        AgentProfile(
            profile_id="sales",
            tool_ids=["search", "search"],
            prompt_version_id="sales:v1",
            budget_policy_id="standard",
            approval_policy_id="safe-default",
        )


def test_agent_profile_rejects_duplicate_knowledge_base_ids() -> None:
    with pytest.raises(
        ValidationError,
        match="knowledge_base_ids must be unique",
    ):
        AgentProfile(
            profile_id="sales",
            prompt_version_id="sales:v1",
            budget_policy_id="standard",
            approval_policy_id="safe-default",
            knowledge_base_ids=["products", "products"],
        )


def test_agent_profile_rejects_missing_prompt_version_id() -> None:
    with pytest.raises(ValidationError) as exc_info:
        AgentProfile.model_validate(
            {
                "profile_id": "sales",
                "budget_policy_id": "standard",
                "approval_policy_id": "safe-default",
            }
        )

    error = exc_info.value.errors()[0]
    assert error["loc"] == ("prompt_version_id",)
    assert error["type"] == "missing"


def test_prompt_version_preserves_timezone_when_dumped() -> None:
    prompt = PromptVersion.model_validate(
        {
            "prompt_version_id": "sales:v1",
            "content": "You are a sales assistant.",
            "content_hash": ("5ad692242d40db8ddcb431b2890f1f818bad8c675f30c041b6d9b4f6f5af3354"),
            "created_at": "2026-08-25T10:00:00+08:00",
        }
    )

    payload = prompt.model_dump(mode="json")

    assert payload["created_at"] == "2026-08-25T10:00:00+08:00"


def test_prompt_version_cleans_variable_names() -> None:
    prompt = PromptVersion(
        prompt_version_id="routing:v1",
        content="Route {{user_request}} using {{retrieved_context}}.",
        content_hash="c8d399354c36ea50b6bf14a34102c935ec40b859012bd31c5f373c4550715d9c",
        variables=(" user_request ", "retrieved_context"),
        created_at=datetime.fromisoformat("2026-08-29T10:00:00+08:00"),
    )

    assert prompt.variables == ("user_request", "retrieved_context")


def test_prompt_version_rejects_blank_variable_name() -> None:
    with pytest.raises(
        ValidationError,
        match="variables must not contain blank names",
    ):
        PromptVersion(
            prompt_version_id="routing:v1",
            content="Route {{user_request}}.",
            content_hash="9377b873c552c72bc42d3b6acfdadd0a746dd658c2ac376a3ce7832d66c16ccf",
            variables=("   ",),
            created_at=datetime.fromisoformat("2026-08-29T10:00:00+08:00"),
        )


def test_prompt_version_rejects_variables_duplicated_after_cleaning() -> None:
    with pytest.raises(
        ValidationError,
        match="variables must be unique",
    ):
        PromptVersion(
            prompt_version_id="routing:v1",
            content="Route {{user_request}}.",
            content_hash="9377b873c552c72bc42d3b6acfdadd0a746dd658c2ac376a3ce7832d66c16ccf",
            variables=("user_request", " user_request "),
            created_at=datetime.fromisoformat("2026-08-29T10:00:00+08:00"),
        )


def test_agent_profile_defaults_version_to_one() -> None:
    profile = AgentProfile(
        profile_id="sales",
        prompt_version_id="sales:v1",
        budget_policy_id="standard",
        approval_policy_id="safe-default",
    )

    assert profile.version == 1


def test_agent_profile_patch_excludes_unset_tool_ids() -> None:
    patch = AgentProfilePatch(expected_version=1)

    payload = patch.model_dump(exclude_unset=True)

    assert payload == {"expected_version": 1}


def test_agent_profile_patch_rejects_null_tool_ids() -> None:
    with pytest.raises(ValidationError) as exc_info:
        AgentProfilePatch.model_validate(
            {
                "expected_version": 1,
                "tool_ids": None,
            }
        )

    error = exc_info.value.errors()[0]
    assert error["loc"] == ("tool_ids",)
    assert error["type"] == "list_type"
