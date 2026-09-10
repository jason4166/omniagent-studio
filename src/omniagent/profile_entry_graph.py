"""Bounded route decision stage for the incremental Day14 migration."""

from typing import Literal, TypedDict, cast

from langgraph.errors import GraphRecursionError
from langgraph.graph import END, START, StateGraph
from pydantic import ValidationError

from omniagent.grounding import (
    DOCUMENT_TRUST_BOUNDARY_INSTRUCTION,
    ContextPack,
    ContextPackAuthorizationError,
    ContextPackIntegrityError,
    GroundingDecision,
    build_context_pack,
    decide_grounding_outcome,
    render_context_pack_data,
)
from omniagent.grounding_runtime import (
    GROUNDING_RESPONSE_INSTRUCTION,
    GroundingProposal,
    RetrievalHitProvider,
    evaluate_grounding_proposal,
    parse_grounding_proposal,
)
from omniagent.llm import (
    LLMInvalidOutputError,
    LLMMessage,
    LLMProvider,
    LLMProviderError,
    LLMProviderUnavailableError,
    LLMRequest,
    RouteDecision,
    parse_route_decision,
)
from omniagent.profiles import AgentProfile
from omniagent.prompts import PromptRenderError, PromptVersionRepository, render_prompt
from omniagent.repositories import AgentProfileRepository
from omniagent.resource_budget import ResourceBudget, accumulate_reported_tokens
from omniagent.runtime import (
    RuntimeBudgetPolicy,
    RuntimeErrorDetail,
    RuntimeResult,
    runtime_result_from_grounding_decision,
)
from omniagent.tool_registry import ToolRegistry
from omniagent.tooling import BudgetPolicy, ToolCall, ToolResult, generate_call_id

GRAPH_RECURSION_LIMIT = 9

ENTRY_ERROR_MESSAGES = {
    "resource_budget_unavailable": "Hard token or cost budget enforcement is not available",
    "profile_not_found": "Agent profile was not found",
    "profile_disabled": "Agent profile is disabled",
    "profile_load_failed": "Agent profile could not be loaded",
    "profile_identity_mismatch": "Agent profile identity did not match the request",
    "budget_policy_not_found": "Runtime budget policy was not found",
    "budget_policy_identity_mismatch": "Runtime budget policy identity did not match the profile",
    "prompt_not_found": "Prompt version was not found",
    "prompt_load_failed": "Prompt version could not be loaded",
    "prompt_identity_mismatch": "Prompt version identity did not match the profile",
    "prompt_render_failed": "Prompt version could not be rendered",
    "entry_not_ready": "Agent entry checks have not passed",
    "decision_not_prepared": "Model request has not been prepared",
    "invalid_decision_state": "Model request or budget failed validation",
    "budget_exceeded": "Runtime budget is exhausted",
    "invalid_model_output": "Model output failed validation",
    "provider_unavailable": "LLM provider is unavailable",
    "provider_error": "LLM provider request failed",
    "route_not_implemented": "This route is not implemented in the incremental graph",
    "invalid_graph_state": "Graph output state failed validation",
    "invalid_tool_state": "Tool execution state failed validation",
    "invalid_tool_result": "Tool registry returned an invalid result",
    "tool_execution_failed": "Tool execution failed",
    "retrieval_not_allowed": "Knowledge retrieval is not allowed for this profile",
    "invalid_retrieval_state": "Retrieval state failed validation",
    "retrieval_failed": "Knowledge retrieval failed",
    "unauthorized_citation": "Retrieved evidence is outside the authorized knowledge bases",
    "context_mismatch": "Retrieved evidence identity failed validation",
    "context_preparation_failed": "Retrieved evidence could not be prepared",
    "invalid_grounding_state": "Grounding state failed validation",
}


class ProfileSnapshot(TypedDict):
    profile_id: str
    enabled: bool
    prompt_version_id: str
    budget_policy_id: str
    version: int
    tool_ids: list[str]
    knowledge_base_ids: list[str]
    approval_policy_id: str


class BudgetSnapshot(TypedDict):
    budget_policy_id: str
    max_model_calls: int
    max_tool_calls: int
    max_steps: int


class EntryInput(TypedDict):
    profile_id: str
    thread_id: str
    message: str


class EntryState(EntryInput):
    resource_budget: dict[str, int | None]
    reported_total_tokens: int | None
    reported_cost_microusd: int | None
    profile: ProfileSnapshot | None
    status: Literal[
        "pending",
        "ready",
        "prepared",
        "decided",
        "tool_prepared",
        "tool_finished",
        "retrieved",
        "proposed",
        "validated",
        "rejected",
        "failed",
    ]
    error_code: str | None
    graph_steps_used: int
    business_steps_used: int
    model_calls_used: int
    tool_calls_used: int
    budget: BudgetSnapshot | None
    request: dict[str, object] | None
    decision: dict[str, object] | None
    result: dict[str, object] | None
    tool_call: dict[str, object] | None
    tool_result: dict[str, object] | None
    proposal: dict[str, object] | None
    grounding_decision: dict[str, object] | None
    context_pack: dict[str, object] | None


class ProfileEntryGraph:
    def __init__(
        self,
        repository: AgentProfileRepository,
        *,
        prompt_repository: PromptVersionRepository,
        budget_policies: dict[str, RuntimeBudgetPolicy],
        model: str,
        provider: LLMProvider,
        tool_registry: ToolRegistry,
        actor_role: str,
        retriever: RetrievalHitProvider,
        max_content_characters: int,
        resource_budget: ResourceBudget | None = None,
    ) -> None:
        if max_content_characters < 1:
            raise ValueError("max_content_characters must be positive")
        self._resource_budget = resource_budget if resource_budget is not None else ResourceBudget()
        self._repository = repository
        self._prompt_repository = prompt_repository
        self._budget_policies = budget_policies
        self._model = model
        self._provider = provider
        self._tool_registry = tool_registry
        self._actor_role = actor_role
        self._retriever = retriever
        self._max_content_characters = max_content_characters
        builder = StateGraph(EntryState, input_schema=EntryInput)
        builder.add_node("load_profile", self.load_profile)
        builder.add_node("guard_input", self.guard_input)
        builder.add_node("prepare_decision", self.prepare_decision)
        builder.add_node("decide", self.decide)
        builder.add_node("respond", self.respond)
        builder.add_node("prepare_tool", self.prepare_tool)
        builder.add_node("execute_tool", self.execute_tool)
        builder.add_node("retrieve", self.retrieve)
        builder.add_node("generate_answer", self.generate_answer)
        builder.add_node("validate_answer", self.validate_answer)
        builder.add_edge(START, "load_profile")
        builder.add_edge("load_profile", "guard_input")
        builder.add_conditional_edges(
            "guard_input",
            self.route_after_guard,
            {"prepare": "prepare_decision", "stop": "respond"},
        )
        builder.add_conditional_edges(
            "prepare_decision",
            self.route_after_preparation,
            {"decide": "decide", "stop": "respond"},
        )
        builder.add_conditional_edges(
            "decide",
            self.route_after_decision,
            {"tool": "prepare_tool", "retrieve": "retrieve", "respond": "respond"},
        )
        builder.add_conditional_edges(
            "prepare_tool",
            self.route_after_tool_preparation,
            {"execute": "execute_tool", "stop": "respond"},
        )
        builder.add_edge("execute_tool", "respond")
        builder.add_conditional_edges(
            "retrieve",
            self.route_after_retrieval,
            {"generate": "generate_answer", "respond": "respond"},
        )
        builder.add_conditional_edges(
            "generate_answer",
            self.route_after_generation,
            {"validate": "validate_answer", "respond": "respond"},
        )
        builder.add_edge("validate_answer", "respond")
        builder.add_edge("respond", END)
        self._graph = builder.compile().with_config({"recursion_limit": GRAPH_RECURSION_LIMIT})

    def run(self, profile_id: str, thread_id: str, message: str) -> RuntimeResult:
        try:
            state = self.run_state(profile_id, thread_id, message)
        except GraphRecursionError:
            return RuntimeResult(
                profile_id=profile_id,
                thread_id=thread_id,
                status="failed",
                error=RuntimeErrorDetail(
                    code="graph_step_limit_exceeded",
                    message="Graph execution reached its step limit",
                ),
            )
        return RuntimeResult.model_validate(state["result"])

    def run_state(self, profile_id: str, thread_id: str, message: str) -> EntryState:
        initial: EntryInput = {
            "profile_id": profile_id,
            "thread_id": thread_id,
            "message": message,
        }
        return cast(
            EntryState,
            self._graph.invoke(initial, {"recursion_limit": GRAPH_RECURSION_LIMIT}),
        )

    def load_profile(self, state: EntryInput) -> dict[str, object]:
        update: dict[str, object] = {
            "resource_budget": self._resource_budget.model_dump(mode="json"),
            "reported_total_tokens": 0,
            "reported_cost_microusd": 0,
            "profile": None,
            "status": "pending",
            "error_code": None,
            "graph_steps_used": 1,
            "business_steps_used": 0,
            "model_calls_used": 0,
            "tool_calls_used": 0,
            "budget": None,
            "request": None,
            "decision": None,
            "result": None,
            "tool_call": None,
            "tool_result": None,
            "context_pack": None,
            "proposal": None,
            "grounding_decision": None,
        }
        try:
            profile = self._repository.get(state["profile_id"])
        except Exception:
            update.update(status="failed", error_code="profile_load_failed")
            return update

        snapshot: ProfileSnapshot | None = None
        if profile is not None:
            snapshot = {
                "profile_id": profile.profile_id,
                "enabled": profile.enabled,
                "prompt_version_id": profile.prompt_version_id,
                "budget_policy_id": profile.budget_policy_id,
                "version": profile.version,
                "tool_ids": list(profile.tool_ids),
                "knowledge_base_ids": list(profile.knowledge_base_ids),
                "approval_policy_id": profile.approval_policy_id,
            }
        update["profile"] = snapshot
        return update

    def guard_input(self, state: EntryState) -> dict[str, object]:
        steps_used = state["graph_steps_used"] + 1
        if state["status"] == "failed":
            return {"graph_steps_used": steps_used}

        profile = state["profile"]
        error_code = None
        if profile is None:
            error_code = "profile_not_found"
        elif profile["profile_id"] != state["profile_id"]:
            error_code = "profile_identity_mismatch"
        elif not profile["enabled"]:
            error_code = "profile_disabled"

        return {
            "status": "ready" if error_code is None else "rejected",
            "error_code": error_code,
            "graph_steps_used": steps_used,
        }

    def route_after_guard(self, state: EntryState) -> Literal["prepare", "stop"]:
        return "prepare" if state["status"] == "ready" else "stop"

    def prepare_decision(self, state: EntryState) -> dict[str, object]:
        profile = state["profile"]
        if state["status"] != "ready" or profile is None:
            return self._preparation_failure(state, "entry_not_ready")

        budget = self._budget_policies.get(profile["budget_policy_id"])
        if budget is None:
            return self._preparation_failure(state, "budget_policy_not_found")
        if budget.budget_policy_id != profile["budget_policy_id"]:
            return self._preparation_failure(state, "budget_policy_identity_mismatch")

        try:
            prompt = self._prompt_repository.get(profile["prompt_version_id"])
        except Exception:
            return self._preparation_failure(state, "prompt_load_failed")
        if prompt is None:
            return self._preparation_failure(state, "prompt_not_found")
        if prompt.prompt_version_id != profile["prompt_version_id"]:
            return self._preparation_failure(state, "prompt_identity_mismatch")

        try:
            rendered_prompt = render_prompt(prompt, {})
        except PromptRenderError:
            return self._preparation_failure(state, "prompt_render_failed")

        request = LLMRequest(
            model=self._model,
            messages=[
                LLMMessage(role="system", content=rendered_prompt),
                LLMMessage(role="user", content=state["message"]),
            ],
            response_schema=RouteDecision.model_json_schema(),
        )
        snapshot: BudgetSnapshot = {
            "budget_policy_id": budget.budget_policy_id,
            "max_model_calls": budget.max_model_calls,
            "max_tool_calls": budget.max_tool_calls,
            "max_steps": budget.max_steps,
        }
        return {
            "status": "prepared",
            "error_code": None,
            "request": request.model_dump(mode="json"),
            "budget": snapshot,
            "graph_steps_used": state["graph_steps_used"] + 1,
        }

    def _preparation_failure(self, state: EntryState, code: str) -> dict[str, object]:
        return {
            "status": "failed",
            "error_code": code,
            "request": None,
            "budget": None,
            "graph_steps_used": state["graph_steps_used"] + 1,
        }

    def route_after_preparation(self, state: EntryState) -> Literal["decide", "stop"]:
        return "decide" if state["status"] == "prepared" else "stop"

    def decide(self, state: EntryState) -> dict[str, object]:
        update: dict[str, object] = {
            "graph_steps_used": state["graph_steps_used"] + 1,
            "decision": None,
            "status": "failed",
            "error_code": None,
        }
        if state["status"] != "prepared" or state["budget"] is None or state["request"] is None:
            update["error_code"] = "decision_not_prepared"
            return update

        try:
            budget = RuntimeBudgetPolicy.model_validate(state["budget"])
            request = LLMRequest.model_validate(state["request"])
        except ValidationError:
            update["error_code"] = "invalid_decision_state"
            return update

        if (
            state["model_calls_used"] >= budget.max_model_calls
            or state["business_steps_used"] >= budget.max_steps
        ):
            update.update(status="rejected", error_code="budget_exceeded")
            return update

        if self._resource_budget.requires_enforcement:
            update.update(status="rejected", error_code="resource_budget_unavailable")
            return update
        update["reported_total_tokens"] = None
        update["reported_cost_microusd"] = None
        update["model_calls_used"] = state["model_calls_used"] + 1
        update["business_steps_used"] = state["business_steps_used"] + 1
        try:
            response = self._provider.generate(request)
            update["reported_total_tokens"] = accumulate_reported_tokens(
                state["reported_total_tokens"], response.usage
            )
            decision = parse_route_decision(response)
            if decision.route in ("direct", "clarify") and decision.output_text is None:
                raise LLMInvalidOutputError
        except LLMInvalidOutputError:
            update["error_code"] = "invalid_model_output"
        except LLMProviderUnavailableError:
            update["error_code"] = "provider_unavailable"
        except LLMProviderError:
            update["error_code"] = "provider_error"
        except Exception:
            update["error_code"] = "provider_error"
        else:
            update.update(status="decided", decision=decision.model_dump(mode="json"))
        return update

    def respond(self, state: EntryState) -> dict[str, object]:
        result = self._build_result(state)
        return {
            "result": result.model_dump(mode="json"),
            "graph_steps_used": state["graph_steps_used"] + 1,
        }

    def _build_result(self, state: EntryState) -> RuntimeResult:
        if state["status"] == "validated":
            try:
                grounding_decision = GroundingDecision.model_validate(state["grounding_decision"])
            except ValidationError:
                return self._error_result(
                    state, status="failed", code="invalid_grounding_state", route="retrieve"
                )
            return runtime_result_from_grounding_decision(
                profile_id=state["profile_id"],
                thread_id=state["thread_id"],
                decision=grounding_decision,
            )
        if state["status"] == "retrieved":
            return self._retrieval_runtime_result(state)
        if state["status"] == "tool_finished":
            return self._tool_runtime_result(state)
        if state["status"] in ("failed", "rejected"):
            return self._error_result(
                state,
                status=state["status"],
                code=state["error_code"] or "invalid_graph_state",
                route=(
                    "retrieve"
                    if state["decision"] is not None
                    and state["decision"].get("route") == "retrieve"
                    else "tool"
                    if state["tool_call"] is not None
                    else None
                ),
            )
        if state["status"] != "decided" or state["error_code"] is not None:
            return self._error_result(state, status="failed", code="invalid_graph_state")

        try:
            decision = RouteDecision.model_validate(state["decision"])
        except ValidationError:
            return self._error_result(state, status="failed", code="invalid_model_output")

        if decision.route not in ("direct", "clarify"):
            return self._error_result(
                state,
                status="rejected",
                code="route_not_implemented",
                route=decision.route,
            )
        if decision.output_text is None:
            return self._error_result(state, status="failed", code="invalid_model_output")

        return RuntimeResult(
            profile_id=state["profile_id"],
            thread_id=state["thread_id"],
            status="succeeded",
            route=decision.route,
            output_text=decision.output_text,
        )

    def _error_result(
        self,
        state: EntryState,
        *,
        status: Literal["rejected", "failed"],
        code: str,
        route: Literal["direct", "retrieve", "tool", "clarify"] | None = None,
    ) -> RuntimeResult:
        if code not in ENTRY_ERROR_MESSAGES:
            code = "invalid_graph_state"
            status = "failed"
        return RuntimeResult(
            profile_id=state["profile_id"],
            thread_id=state["thread_id"],
            status=status,
            route=route,
            error=RuntimeErrorDetail(code=code, message=ENTRY_ERROR_MESSAGES[code]),
        )

    def route_after_decision(self, state: EntryState) -> Literal["tool", "retrieve", "respond"]:
        if state["status"] == "decided" and state["decision"] is not None:
            if state["decision"].get("route") == "tool":
                return "tool"
            if state["decision"].get("route") == "retrieve":
                return "retrieve"
        return "respond"

    def prepare_tool(self, state: EntryState) -> dict[str, object]:
        update: dict[str, object] = {
            "graph_steps_used": state["graph_steps_used"] + 1,
            "status": "failed",
            "error_code": "invalid_tool_state",
            "tool_call": None,
            "tool_result": None,
        }
        if state["status"] != "decided":
            return update
        try:
            decision = RouteDecision.model_validate(state["decision"])
        except ValidationError:
            return update
        if decision.route != "tool" or decision.tool_name is None or decision.args is None:
            return update
        call = ToolCall(
            call_id=generate_call_id(),
            tool_name=decision.tool_name,
            arguments=decision.args,
            profile_id=state["profile_id"],
            thread_id=state["thread_id"],
        )
        update.update(
            status="tool_prepared", error_code=None, tool_call=call.model_dump(mode="json")
        )
        return update

    def route_after_tool_preparation(self, state: EntryState) -> Literal["execute", "stop"]:
        return "execute" if state["status"] == "tool_prepared" else "stop"

    def execute_tool(self, state: EntryState) -> dict[str, object]:
        update: dict[str, object] = {
            "graph_steps_used": state["graph_steps_used"] + 1,
            "status": "failed",
            "error_code": "invalid_tool_state",
            "tool_result": None,
        }
        if state["status"] != "tool_prepared":
            return update
        try:
            call = ToolCall.model_validate(state["tool_call"])
            profile = AgentProfile.model_validate(state["profile"])
            budget = RuntimeBudgetPolicy.model_validate(state["budget"])
        except ValidationError:
            return update
        if (
            call.profile_id != state["profile_id"]
            or call.thread_id != state["thread_id"]
            or not profile.enabled
        ):
            return update
        if (
            state["tool_calls_used"] >= budget.max_tool_calls
            or state["business_steps_used"] >= budget.max_steps
        ):
            update.update(status="rejected", error_code="budget_exceeded")
            return update

        # Count attempts at the controlled execution boundary, including rejections.
        update["tool_calls_used"] = state["tool_calls_used"] + 1
        update["business_steps_used"] = state["business_steps_used"] + 1
        try:
            result = self._tool_registry.execute(
                call=call,
                profile=profile,
                actor_role=self._actor_role,
                approval_granted=False,
                budget_policy=BudgetPolicy(
                    budget_policy_id=budget.budget_policy_id, max_calls=budget.max_tool_calls
                ),
                calls_used=state["tool_calls_used"],
            )
        except Exception:
            update["error_code"] = "tool_execution_failed"
            return update
        try:
            result_data = result.model_dump(mode="json")
        except Exception:
            update["error_code"] = "invalid_tool_result"
            return update
        update.update(status="tool_finished", error_code=None, tool_result=result_data)
        return update

    def _tool_runtime_result(self, state: EntryState) -> RuntimeResult:
        try:
            call = ToolCall.model_validate(state["tool_call"])
            result = ToolResult.model_validate(state["tool_result"])
        except ValidationError:
            return self._error_result(
                state, status="failed", code="invalid_tool_result", route="tool"
            )
        if result.call_id != call.call_id or (
            result.status != "succeeded" and result.error is None
        ):
            return self._error_result(
                state, status="failed", code="invalid_tool_result", route="tool"
            )
        error = None
        if result.error is not None:
            error = RuntimeErrorDetail(code=result.error.code, message=result.error.message)
        return RuntimeResult(
            profile_id=state["profile_id"],
            thread_id=state["thread_id"],
            status=result.status,
            route="tool",
            tool_result=result,
            error=error,
        )

    def retrieve(self, state: EntryState) -> dict[str, object]:
        update: dict[str, object] = {
            "status": "failed",
            "error_code": "invalid_retrieval_state",
            "context_pack": None,
            "graph_steps_used": state["graph_steps_used"] + 1,
        }
        if state["status"] != "decided":
            return update
        try:
            decision = RouteDecision.model_validate(state["decision"])
            profile = AgentProfile.model_validate(state["profile"])
            budget = RuntimeBudgetPolicy.model_validate(state["budget"])
        except ValidationError:
            return update
        if (
            decision.route != "retrieve"
            or profile.profile_id != state["profile_id"]
            or not profile.enabled
        ):
            return update
        authorized_ids = tuple(profile.knowledge_base_ids)
        if not authorized_ids:
            update.update(status="rejected", error_code="retrieval_not_allowed")
            return update
        if state["business_steps_used"] >= budget.max_steps:
            update.update(status="rejected", error_code="budget_exceeded")
            return update

        update["business_steps_used"] = state["business_steps_used"] + 1
        try:
            hits = self._retriever.retrieve_hits(list(authorized_ids), state["message"])
        except Exception:
            update["error_code"] = "retrieval_failed"
            return update
        try:
            context_pack = build_context_pack(
                hits,
                authorized_knowledge_base_ids=authorized_ids,
                max_content_characters=self._max_content_characters,
            )
        except ContextPackAuthorizationError:
            update.update(status="rejected", error_code="unauthorized_citation")
        except ContextPackIntegrityError:
            update.update(status="rejected", error_code="context_mismatch")
        except Exception:
            update["error_code"] = "context_preparation_failed"
        else:
            update.update(
                status="retrieved",
                error_code=None,
                context_pack=context_pack.model_dump(mode="json"),
            )
        return update

    def _retrieval_runtime_result(self, state: EntryState) -> RuntimeResult:
        try:
            context_pack = ContextPack.model_validate(state["context_pack"])
        except ValidationError:
            return self._error_result(
                state, status="failed", code="context_mismatch", route="retrieve"
            )
        if not context_pack.evidence:
            return runtime_result_from_grounding_decision(
                profile_id=state["profile_id"],
                thread_id=state["thread_id"],
                decision=decide_grounding_outcome(),
            )
        return self._error_result(
            state, status="failed", code="invalid_grounding_state", route="retrieve"
        )

    def route_after_retrieval(self, state: EntryState) -> Literal["generate", "respond"]:
        if state["status"] == "retrieved" and state["context_pack"] is not None:
            if state["context_pack"].get("evidence"):
                return "generate"
        return "respond"

    def route_after_generation(self, state: EntryState) -> Literal["validate", "respond"]:
        return "validate" if state["status"] == "proposed" else "respond"

    def generate_answer(self, state: EntryState) -> dict[str, object]:
        update: dict[str, object] = {
            "graph_steps_used": state["graph_steps_used"] + 1,
            "status": "failed",
            "error_code": "invalid_grounding_state",
            "proposal": None,
            "grounding_decision": None,
        }
        if state["status"] != "retrieved":
            return update
        try:
            pack = ContextPack.model_validate(state["context_pack"])
            budget = RuntimeBudgetPolicy.model_validate(state["budget"])
            profile = AgentProfile.model_validate(state["profile"])
        except ValidationError:
            return update
        if not pack.evidence or profile.profile_id != state["profile_id"] or not profile.enabled:
            return update
        if any(item.knowledge_base_id not in profile.knowledge_base_ids for item in pack.evidence):
            update.update(status="rejected", error_code="unauthorized_citation")
            return update
        if (
            state["model_calls_used"] >= budget.max_model_calls
            or state["business_steps_used"] >= budget.max_steps
        ):
            update.update(status="rejected", error_code="budget_exceeded")
            return update
        request = LLMRequest(
            model=self._model,
            messages=[
                LLMMessage(
                    role="system",
                    content=(
                        f"{GROUNDING_RESPONSE_INSTRUCTION} {DOCUMENT_TRUST_BOUNDARY_INSTRUCTION}"
                    ),
                ),
                LLMMessage(role="user", content=state["message"]),
                LLMMessage(
                    role="user",
                    content=f"Untrusted context data:\n{render_context_pack_data(pack)}",
                ),
            ],
            response_schema=GroundingProposal.model_json_schema(),
        )
        if self._resource_budget.requires_enforcement:
            update.update(status="rejected", error_code="resource_budget_unavailable")
            return update
        update["reported_total_tokens"] = None
        update["reported_cost_microusd"] = None
        update["model_calls_used"] = state["model_calls_used"] + 1
        update["business_steps_used"] = state["business_steps_used"] + 1
        try:
            response = self._provider.generate(request)
            update["reported_total_tokens"] = accumulate_reported_tokens(
                state["reported_total_tokens"], response.usage
            )
            proposal = parse_grounding_proposal(response)
        except LLMInvalidOutputError:
            update["error_code"] = "invalid_model_output"
        except LLMProviderUnavailableError:
            update["error_code"] = "provider_unavailable"
        except Exception:
            update["error_code"] = "provider_error"
        else:
            update.update(
                status="proposed", error_code=None, proposal=proposal.model_dump(mode="json")
            )
        return update

    def validate_answer(self, state: EntryState) -> dict[str, object]:
        update: dict[str, object] = {
            "graph_steps_used": state["graph_steps_used"] + 1,
            "status": "failed",
            "error_code": "invalid_grounding_state",
            "grounding_decision": None,
        }
        if state["status"] != "proposed":
            return update
        try:
            proposal = GroundingProposal.model_validate(state["proposal"])
            pack = ContextPack.model_validate(state["context_pack"])
            profile = AgentProfile.model_validate(state["profile"])
            if profile.profile_id != state["profile_id"] or not profile.enabled:
                return update
            if any(
                item.knowledge_base_id not in profile.knowledge_base_ids for item in pack.evidence
            ):
                update.update(status="rejected", error_code="unauthorized_citation")
                return update
            decision = evaluate_grounding_proposal(
                proposal,
                context_pack=pack,
                authorized_knowledge_base_ids=profile.knowledge_base_ids,
            )
        except Exception:
            return update
        update.update(
            status="validated", error_code=None, grounding_decision=decision.model_dump(mode="json")
        )
        return update
