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
            "created_at": "2026-08-25T10:00:00+08:00",
        }
    )

    payload = prompt.model_dump(mode="json")

    assert payload["created_at"] == "2026-08-25T10:00:00+08:00"


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
