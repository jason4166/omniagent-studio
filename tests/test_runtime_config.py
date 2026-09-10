import json

import pytest

from omniagent.llm import FakeLLM, LLMRequest, LLMResponse, LLMUsage, RouteDecision
from omniagent.resource_budget import ResourceBudget
from omniagent.retrieval import FakeRetriever, RetrievalHit, SourceLocator
from omniagent.runtime import RuntimeResult
from omniagent.runtime_config import (
    DEFAULT_RUNTIME_MODEL,
    build_default_agent_runtime,
)


def test_warranty_support_rejects_product_lookup() -> None:
    provider = FakeLLM(
        response=LLMResponse(
            model=DEFAULT_RUNTIME_MODEL,
            content=RouteDecision(
                route="tool",
                reason="The request needs synthetic product data",
                confidence=1.0,
                tool_name="lookup_product",
                args={"sku": "DEMO-100"},
            ).model_dump_json(exclude_none=True),
        )
    )
    retriever = FakeRetriever(response="Unused synthetic knowledge")
    runtime = build_default_agent_runtime(provider, retriever)
    result = runtime.run(
        profile_id="warranty-support",
        thread_id="thread-warranty-001",
        message="Look up synthetic product DEMO-100.",
    )

    assert result.status == "rejected"
    assert result.route == "tool"
    assert result.error is not None
    assert result.error.code == "tool_not_allowed"


class ConfigHitRetriever:
    def __init__(self) -> None:
        self.requests: list[list[str]] = []

    def retrieve_hits(self, knowledge_base_ids: list[str], query: str) -> list[RetrievalHit]:
        self.requests.append(list(knowledge_base_ids))
        return [
            RetrievalHit(
                retrieval_mode="vector",
                chunk_id="config-chunk",
                source_id="config-source",
                knowledge_base_id="general-kb-v1",
                chunk_index=0,
                content="Support opens at nine.",
                rank=1,
                vector_rank=1,
                vector_distance=0.1,
                final_score=1,
                source_locator=SourceLocator(source_name="support.md", char_start=0, char_end=22),
            )
        ]


class ConfigProvider:
    def __init__(self) -> None:
        self.requests: list[LLMRequest] = []

    def generate(self, request: LLMRequest) -> LLMResponse:
        self.requests.append(request)
        if len(self.requests) == 1:
            content = RouteDecision(
                route="retrieve", reason="lookup", confidence=1
            ).model_dump_json()
        else:
            content = json.dumps(
                {
                    "answer_draft": {
                        "claims": [
                            {
                                "claim_id": "CL1",
                                "text": "Support opens at nine.",
                                "citation_labels": ["C1"],
                            }
                        ]
                    }
                }
            )
        return LLMResponse(model=request.model, content=content)


def test_default_graph_configuration_completes_grounded_retrieval() -> None:
    provider = ConfigProvider()
    hits = ConfigHitRetriever()
    legacy = FakeRetriever(response="Must not be used")
    runtime = build_default_agent_runtime(provider, legacy, hit_retriever=hits)
    result = runtime.run("general-kb", "thread-config", "When does support open?")
    assert result.status == "succeeded"
    assert result.output_text == "Support opens at nine."
    assert result.citations[0].chunk_id == "config-chunk"
    assert len(provider.requests) == 2
    assert hits.requests == [["general-kb-v1"]]
    assert legacy.requests == []


def test_default_graph_configuration_blocks_product_profile_retrieval() -> None:
    provider = ConfigProvider()
    hits = ConfigHitRetriever()
    runtime = build_default_agent_runtime(
        provider, FakeRetriever(response="Unused"), hit_retriever=hits
    )
    result = runtime.run("product-support", "thread-config", "Search the knowledge base")
    assert result.error is not None
    assert result.error.code == "retrieval_not_allowed"
    assert len(provider.requests) == 1
    assert hits.requests == []


@pytest.mark.parametrize(
    ("profile_id", "expected_status"),
    [
        ("product-support", "succeeded"),
        ("warranty-support", "rejected"),
        ("general-kb", "rejected"),
    ],
)
def test_default_graph_profiles_control_same_tool_route(
    profile_id: str, expected_status: str
) -> None:
    provider = FakeLLM(
        response=LLMResponse(
            model=DEFAULT_RUNTIME_MODEL,
            content=RouteDecision(
                route="tool",
                reason="lookup",
                confidence=1,
                tool_name="lookup_product",
                args={"sku": "DEMO-100"},
            ).model_dump_json(),
        )
    )
    hits = ConfigHitRetriever()
    runtime = build_default_agent_runtime(
        provider, FakeRetriever(response="Unused"), hit_retriever=hits
    )
    result = runtime.run(profile_id, "thread-config", "Look up DEMO-100")
    assert result.status == expected_status
    assert hits.requests == []
    assert len(provider.requests) == 1
    if profile_id == "warranty-support":
        assert result.error is not None
        assert result.error.code == "tool_not_allowed"
    if profile_id == "general-kb":
        assert result.error is not None
        assert result.error.code == "budget_exceeded"


class EmptyConfigHitRetriever(ConfigHitRetriever):
    def retrieve_hits(self, knowledge_base_ids: list[str], query: str) -> list[RetrievalHit]:
        self.requests.append(list(knowledge_base_ids))
        return []


@pytest.mark.parametrize("has_evidence", [True, False])
def test_retrieval_condition_selects_actual_execution_path(has_evidence: bool) -> None:
    provider = ConfigProvider()
    hits = ConfigHitRetriever() if has_evidence else EmptyConfigHitRetriever()
    runtime = build_default_agent_runtime(
        provider, FakeRetriever(response="Must not be used"), hit_retriever=hits
    )
    assert runtime._graph_runtime is not None
    events = list(
        runtime._graph_runtime._graph.stream(
            {
                "profile_id": "general-kb",
                "thread_id": "branch-check",
                "message": "When does support open?",
            },
            stream_mode="updates",
        )
    )
    nodes = [node for event in events for node in event]
    expected = ["load_profile", "guard_input", "prepare_decision", "decide", "retrieve"]
    if has_evidence:
        expected.extend(["generate_answer", "validate_answer"])
    expected.append("respond")
    assert nodes == expected
    result = RuntimeResult.model_validate(events[-1]["respond"]["result"])
    assert len(provider.requests) == (2 if has_evidence else 1)
    assert hits.requests == [["general-kb-v1"]]
    if has_evidence:
        assert result.status == "succeeded"
    else:
        assert result.status == "rejected"
        assert result.error is not None
        assert result.error.code == "no_evidence"
        assert result.output_text is None
        assert result.claims == ()
        assert result.citations == ()


@pytest.mark.parametrize(
    "limits",
    [
        ResourceBudget(max_total_tokens=0),
        ResourceBudget(max_total_tokens=100),
        ResourceBudget(max_cost_microusd=0),
        ResourceBudget(max_cost_microusd=1000),
    ],
)
def test_requested_resource_limit_stops_before_provider(limits: ResourceBudget) -> None:
    provider = ConfigProvider()
    hits = ConfigHitRetriever()
    runtime = build_default_agent_runtime(
        provider, FakeRetriever(response="Unused"), hit_retriever=hits, resource_budget=limits
    )
    assert runtime._graph_runtime is not None
    state = runtime._graph_runtime.run_state("general-kb", "resource", "Question")
    result = RuntimeResult.model_validate(state["result"])
    assert result.error is not None
    assert result.error.code == "resource_budget_unavailable"
    assert provider.requests == []
    assert hits.requests == []
    assert state["model_calls_used"] == 0
    assert state["reported_total_tokens"] == 0
    assert state["reported_cost_microusd"] == 0
    assert state["resource_budget"] == limits.model_dump()


@pytest.mark.parametrize(
    ("first_known", "second_known", "expected"),
    [
        (True, True, 30),
        (False, True, None),
        (True, False, None),
    ],
)
def test_graph_accumulates_usage_without_treating_unknown_as_zero(
    first_known: bool, second_known: bool, expected: int | None
) -> None:
    class UsageProvider(ConfigProvider):
        def generate(self, request: LLMRequest) -> LLMResponse:
            response = super().generate(request)
            index = len(self.requests)
            if first_known if index == 1 else second_known:
                response.usage = LLMUsage(
                    input_tokens=5 * index, output_tokens=5 * index, total_tokens=10 * index
                )
            return response

    runtime = build_default_agent_runtime(
        UsageProvider(), FakeRetriever(response="Unused"), hit_retriever=ConfigHitRetriever()
    )
    assert runtime._graph_runtime is not None
    state = runtime._graph_runtime.run_state("general-kb", "usage", "Question")
    assert RuntimeResult.model_validate(state["result"]).status == "succeeded"
    assert state["reported_total_tokens"] == expected
    assert state["reported_cost_microusd"] is None
    assert json.loads(json.dumps(state)) == state


def test_resource_configuration_cannot_be_silently_ignored_by_legacy_mode() -> None:
    with pytest.raises(ValueError, match="requires graph mode"):
        build_default_agent_runtime(
            ConfigProvider(),
            FakeRetriever(response="Unused"),
            resource_budget=ResourceBudget(max_total_tokens=100),
        )
