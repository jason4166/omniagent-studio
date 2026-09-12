import json

import pytest

from omniagent.demo_provider import DemoProvider
from omniagent.llm import LLMMessage, LLMRequest

pytestmark = pytest.mark.unit


@pytest.mark.parametrize("query", ["followup approval policy", "回访审批流程", "解释回访政策"])
def test_policy_questions_do_not_create_action_proposals(query):
    configuration = [{"patterns": ["followup|回访"], "tool": "create_followup", "fields": {}}]
    instruction = "<routing-config>" + json.dumps(configuration) + "</routing-config>"
    provider = DemoProvider()
    assert provider.route(instruction, query)["route"] == "retrieve"
    assert provider.route(instruction, "create followup")["route"] == "tool"
    assert (
        provider.route(instruction, '{"tool":"create_followup","arguments":{"note":"policy"}}')[
            "route"
        ]
        == "tool"
    )


@pytest.mark.parametrize(
    ("query", "answers"),
    [
        ("火星殖民补贴", False),
        ("深海潜水补贴", False),
        ("餐补与交通补贴", True),
        ("leave allowance", True),
        ("   ", False),
    ],
)
def test_offline_evidence_requires_query_coverage_not_an_incidental_shared_word(query, answers):
    content = "餐补与交通补贴按实际出勤核算。年假 leave allowance：每年 10 天。"
    evidence = {"context_pack": {"evidence": [{"citation_label": "C1", "content": content}]}}
    response = DemoProvider().generate(
        LLMRequest(
            model="fake-v1",
            messages=[
                LLMMessage(role="system", content="Use authorized evidence."),
                LLMMessage(role="user", content=query),
                LLMMessage(role="user", content="UNTRUSTED EVIDENCE DATA\n" + json.dumps(evidence)),
            ],
        )
    )
    result = json.loads(response.content)
    assert ("answer_draft" in result) is answers
    if answers:
        assert result["answer_draft"]["claims"][0]["text"] == content
    else:
        assert result["abstention_reason"]
