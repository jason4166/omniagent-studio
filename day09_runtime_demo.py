from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
SRC_ROOT = PROJECT_ROOT / "src"
sys.path.insert(0, str(SRC_ROOT))

from omniagent.llm import (  # noqa: E402
    LLMProviderError,
    LLMRequest,
    LLMResponse,
    LLMUnknownModelError,
    RouteDecision,
)
from omniagent.retrieval import FakeRetriever  # noqa: E402
from omniagent.runtime_config import (  # noqa: E402
    DEFAULT_RUNTIME_MODEL,
    build_default_agent_runtime,
)


class SequenceFakeLLM:
    def __init__(self, responses: list[LLMResponse]) -> None:
        self._responses = responses.copy()
        self.requests: list[LLMRequest] = []

    def generate(self, request: LLMRequest) -> LLMResponse:
        self.requests.append(request)
        if not self._responses:
            raise LLMProviderError("No synthetic response remains")

        response = self._responses.pop(0)
        if request.model != response.model:
            raise LLMUnknownModelError
        return response


def main() -> None:
    provider = SequenceFakeLLM(
        responses=[
            LLMResponse(
                model=DEFAULT_RUNTIME_MODEL,
                content=RouteDecision(
                    route="direct",
                    reason="The synthetic greeting needs no external capability",
                    confidence=1.0,
                    output_text="Hello from the synthetic general knowledge profile.",
                ).model_dump_json(exclude_none=True),
            ),
            LLMResponse(
                model=DEFAULT_RUNTIME_MODEL,
                content=RouteDecision(
                    route="tool",
                    reason="Synthetic product data is required",
                    confidence=1.0,
                    tool_name="lookup_product",
                    args={"sku": "DEMO-100"},
                ).model_dump_json(exclude_none=True),
            ),
        ]
    )
    retriever = FakeRetriever(response="Unused synthetic knowledge")
    runtime = build_default_agent_runtime(provider, retriever)

    general_result = runtime.run(
        profile_id="general-kb",
        thread_id="demo-thread-general",
        message="Say hello without using a tool.",
    )
    product_result = runtime.run(
        profile_id="product-support",
        thread_id="demo-thread-product",
        message="Look up synthetic product DEMO-100.",
    )

    print("general_result =", general_result.model_dump_json())
    print("product_result =", product_result.model_dump_json())
    print("model_calls =", len(provider.requests))
    print("retriever_calls =", len(retriever.requests))


if __name__ == "__main__":
    main()
