import pytest
from pydantic import ValidationError

from omniagent.conversation import available_capabilities, conversation_reply
from omniagent.identity import DevUserContext
from omniagent.llm import RouteDecision
from omniagent.profiles import AgentProfile
from omniagent.tool_registry import ToolRegistry
from omniagent.tooling import ToolDefinition, ToolRisk

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    ("route", "kind"),
    [
        ("retrieve", "capabilities"),
        ("clarify", "greeting"),
        ("direct", "approve_everything"),
    ],
)
def test_model_conversation_type_cannot_expand_the_route_schema(route, kind):
    with pytest.raises(ValidationError):
        RouteDecision(route=route, reason="test", confidence=1, conversation_kind=kind)


def test_capabilities_follow_effective_approval_policy_and_not_stale_descriptions():
    profile = AgentProfile(
        profile_id="renamed-profile",
        name="团队助手",
        description="STALE_PROMISE of unlimited writes",
        knowledge_base_ids=["sales-kb"],
        tool_ids=["lookup_customer", "create_followup", "request_discount"],
        prompt_version_id="private-prompt",
        budget_policy_id="standard",
        approval_policy_id="safe-default",
    )
    actor = DevUserContext(user_id="example", role="member", profile_ids=(profile.profile_id,))
    registry = ToolRegistry()

    class NoExecution:
        def execute(self, call):
            pytest.fail("Help cannot execute a business operation")

    for name, role, enabled in (
        ("lookup_customer", "member", True),
        ("create_followup", "admin", True),
        ("request_discount", "member", False),
    ):
        registry.register(
            ToolDefinition(
                name=name,
                risk=ToolRisk.LOW,
                allowed_roles=(role,),
                enabled=enabled,
                requires_approval=False,
            ),
            NoExecution(),
        )
    text = conversation_reply("capabilities", profile, actor, registry)
    assert "查询客户资料：只读查询" in text
    assert "销售与折扣政策" in text
    for forbidden in ("STALE_PROMISE", "private-prompt", "拟定客户回访", "发起折扣申请"):
        assert forbidden not in text
    profile.auto_approve_read = False
    capabilities = available_capabilities(profile, actor, registry)
    assert capabilities[-1].detail == "先生成提案，经人工审批后执行"


def test_help_obeys_profile_permission_and_redacts_configured_presentation(monkeypatch):
    profile = AgentProfile(
        profile_id="private",
        name="团队 secret=synthetic-private-value",
        prompt_version_id="secret-prompt",
        budget_policy_id="standard",
        approval_policy_id="safe-default",
    )
    registry = ToolRegistry()
    from omniagent.errors import PlatformError

    with pytest.raises(PlatformError):
        conversation_reply(
            "capabilities", profile, DevUserContext(user_id="other", role="viewer"), registry
        )
    text = conversation_reply(
        "greeting", profile, DevUserContext(user_id="admin", role="admin"), registry
    )
    assert "synthetic-private-value" not in text
    assert "暂时没有" in text
