import json

import pytest

from omniagent.demo_provider import DemoProvider

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
