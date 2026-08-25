from omniagent.profiles import AgentProfile
from omniagent.repositories import AgentProfileRepository, InMemoryAgentProfileRepository


def test_in_memory_repository_saves_and_gets_profile() -> None:
    repository: AgentProfileRepository = InMemoryAgentProfileRepository()
    profile = AgentProfile(
        profile_id="sales",
        prompt_version_id="sales:v1",
        budget_policy_id="standard",
        approval_policy_id="safe-default",
    )

    repository.save(profile)

    assert repository.get("sales") == profile

def test_in_memory_repository_lists_profiles_in_save_order() -> None:
    repository: AgentProfileRepository = InMemoryAgentProfileRepository()
    sales = AgentProfile(
        profile_id="sales",
        prompt_version_id="sales:v1",
        budget_policy_id="standard",
        approval_policy_id="safe-default",
    )
    hr = AgentProfile(
        profile_id="hr",
        prompt_version_id="hr:v1",
        budget_policy_id="standard",
        approval_policy_id="safe-default",
    )

    repository.save(sales)
    repository.save(hr)

    assert [profile.profile_id for profile in repository.list_all()] == ["sales", "hr"]
