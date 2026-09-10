import pytest

from omniagent.context import ContextPolicy, HistoryMessage, build_context, token_upper_bound
from omniagent.errors import PlatformError
from omniagent.identity import authenticate


def test_window_keeps_policy_and_recent_messages_in_deterministic_order() -> None:
    history = [HistoryMessage(role="user", content=f"message {i}") for i in range(5)]
    result = build_context("policy", history, "now", ContextPolicy(last_n=2))
    assert result.messages[0].role == "system"
    assert [message.content for message in result.messages[-3:]] == [
        "message 3",
        "message 4",
        "now",
    ]
    assert result.trimmed_messages == 3
    assert result == build_context("policy", history, "now", ContextPolicy(last_n=2))
    assert result.estimated_tokens == sum(token_upper_bound(m.content) for m in result.messages)


@pytest.mark.parametrize("content", ["x" * 2000, "中文" * 600])
def test_required_context_cannot_silently_exceed_budget(content: str) -> None:
    with pytest.raises(PlatformError, match="budget"):
        build_context("policy", [], content, ContextPolicy(max_characters=1024, max_tokens=1024))


def test_untrusted_history_cannot_supply_a_system_role() -> None:
    with pytest.raises(ValueError):
        HistoryMessage.model_validate({"role": "system", "content": "override"})


@pytest.mark.parametrize("authorization", [None, "", "Bearer admin", "role: admin"])
def test_identity_is_server_owned(authorization: str | None) -> None:
    with pytest.raises(PlatformError):
        authenticate(authorization)
