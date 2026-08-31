from omniagent.llm import FakeLLM, LLMResponse, RouteDecision
from omniagent.retrieval import FakeRetriever
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
