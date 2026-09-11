"""One durable graph for every profile; policy and effects remain server-owned."""

import json
from collections.abc import Callable
from typing import Literal, NotRequired, TypedDict
from uuid import uuid4

from langchain_core.runnables import RunnableConfig, RunnableLambda
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt
from pydantic import ValidationError
from sqlalchemy import delete, select

from omniagent.approvals import ApprovalService, authorize_tool, needs_approval, policy_hash
from omniagent.context import build_context, token_upper_bound
from omniagent.errors import ErrorCode, PlatformError
from omniagent.execution import execution_key
from omniagent.grounding import (
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
from omniagent.identity import DevUserContext
from omniagent.llm import LLMProvider, LLMRequest, LLMResponse, RouteDecision, parse_route_decision
from omniagent.postgres_repositories import (
    SqlAlchemyPromptVersionRepository,
    SqlAlchemyToolDefinitionRepository,
)
from omniagent.preflight import (
    mapped_read_arguments,
    policy_revisions,
    require_preflight,
    validate_preflight_configuration,
)
from omniagent.profiles import AgentProfile
from omniagent.providers import ControlledProvider, ProviderBinding, model_attempt, model_usage
from omniagent.redaction import contains_secret, redact
from omniagent.reliability import RetryPolicy, dependency_timeout, error_code, retry_call, transient
from omniagent.retrieval import RetrievalHit
from omniagent.runtime import runtime_result_from_grounding_decision
from omniagent.runtime_instructions import EXACT_EVIDENCE_INSTRUCTION, route_instruction
from omniagent.session_models import ApprovalDecision, PreflightSnapshot, SessionData
from omniagent.session_rows import ApprovalRow, EventRow, SessionRow
from omniagent.session_store import SessionStore, digest
from omniagent.telemetry import correlation, span
from omniagent.tool_registry import ToolRegistry
from omniagent.tooling import BudgetPolicy, ToolBusinessError, ToolCall, ToolResult


class DurableState(TypedDict):
    schema_version: int
    thread_id: str
    run_id: str
    decision: dict[str, object] | None
    result: dict[str, object] | None
    approval_id: str | None
    preflight: NotRequired[dict[str, object] | None]


class DurableRuntime:
    def __init__(
        self,
        store: SessionStore,
        saver: BaseCheckpointSaver[str],
        actor: DevUserContext,
        provider: LLMProvider,
        registry: ToolRegistry,
        retriever: RetrievalHitProvider,
        *,
        failure_hook: Callable[[str], None] | None = None,
        reserve_external: Callable[[int], None] | None = None,
        validate_actor: Callable[[], None] | None = None,
    ) -> None:
        self.store = store
        self.saver = saver
        self.actor = actor
        self.provider = (
            provider
            if isinstance(provider, ControlledProvider)
            else ControlledProvider([ProviderBinding("injected", provider)])
        )
        self.registry = registry
        self.retriever = retriever
        self.approvals = ApprovalService(store, registry)
        self.failure_hook = failure_hook
        self.reserve_external = reserve_external
        self.validate_actor = validate_actor
        builder = StateGraph(DurableState)
        for name, handler in (
            ("route", self.route),
            ("retrieve", self.retrieve),
            ("preflight_read", self.preflight_read),
            ("preflight_policy", self.preflight_policy),
            ("propose", self.propose),
            ("approval", self.approval),
            ("execute", self.execute),
            ("respond", self.respond),
        ):
            builder.add_node(name, RunnableLambda(self.observed(name, handler)))
        builder.add_edge(START, "route")
        builder.add_conditional_edges(
            "route",
            self.route_edge,
            {
                "tool": "propose",
                "retrieve": "retrieve",
                "respond": "respond",
                "preflight": "preflight_read",
            },
        )
        builder.add_conditional_edges(
            "propose",
            self.proposal_edge,
            {
                "approval": "approval",
                "execute": "execute",
            },
        )
        builder.add_edge("approval", "execute")
        builder.add_edge("preflight_read", "preflight_policy")
        builder.add_edge("preflight_policy", "propose")
        builder.add_edge("execute", "respond")
        builder.add_edge("retrieve", "respond")
        builder.add_edge("respond", END)
        self.graph = builder.compile(checkpointer=saver)

    def observed(
        self, name: str, handler: Callable[[DurableState], dict[str, object]]
    ) -> Callable[[DurableState], dict[str, object]]:
        def node(state: DurableState) -> dict[str, object]:
            with (
                correlation(
                    thread_id=state["thread_id"], run_id=state["run_id"], node_id=str(uuid4())
                ),
                span("node", node_name=name),
            ):
                return handler(state)

        return node

    def config(self, thread_id: str) -> RunnableConfig:
        return {"configurable": {"thread_id": thread_id}, "recursion_limit": 12}

    def guard(self, state: DurableState) -> tuple[SessionData, AgentProfile]:
        if self.validate_actor is not None:
            self.validate_actor()
        if state.get("schema_version") != 1:
            raise PlatformError(ErrorCode.SCHEMA)
        return self.store.guard(state["thread_id"], state["run_id"], self.actor)

    def fault(self, boundary: str) -> None:
        if self.failure_hook is not None:
            self.failure_hook(boundary)

    def current_tool(self, name: str) -> None:
        with self.store.factory() as db:
            current = SqlAlchemyToolDefinitionRepository(db).get(name)
        if current != self.registry.definition(name):
            raise PlatformError(ErrorCode.CONFLICT, "Tool policy changed; start a new proposal")

    def generate(
        self,
        state: DurableState,
        schema: dict[str, object],
        *,
        evidence: str = "",
    ) -> LLMResponse:
        data, profile = self.guard(state)
        with self.store.factory() as db:
            prompt = SqlAlchemyPromptVersionRepository(db).get(profile.prompt_version_id)
        if prompt is None:
            raise PlatformError(ErrorCode.NOT_FOUND, "Prompt version is missing")
        instruction = prompt.content + (
            "\n" + GROUNDING_RESPONSE_INSTRUCTION + EXACT_EVIDENCE_INSTRUCTION
            if evidence
            else route_instruction(profile, self.registry)
        )
        context = build_context(
            instruction, data.history, data.message, profile.context_policy, evidence_data=evidence
        )

        def reserve() -> None:
            reserved_tokens = (
                context.estimated_tokens + token_upper_bound(json.dumps(schema)) + 1024
            )
            self.store.reserve(
                data.thread_id,
                state["run_id"],
                self.actor,
                "llm",
                tokens=reserved_tokens,
                model=True,
            )
            if self.reserve_external is not None:
                self.reserve_external(reserved_tokens)

        attempt_token = model_attempt.set(reserve)
        usage_token = model_usage.set(
            lambda usage: self.store.record_usage(
                data.thread_id, self.actor, usage, fake=profile.provider_id == "fake"
            )
        )
        try:
            response = self.provider.generate(
                LLMRequest(
                    model=profile.model,
                    messages=context.messages,
                    response_schema=schema,
                    temperature=profile.temperature,
                    max_tokens=1024,
                    timeout_seconds=min(30, max(0.1, data.deadline_at - self.store.clock())),
                )
            )
        finally:
            model_attempt.reset(attempt_token)
            model_usage.reset(usage_token)
        self.guard(state)
        if len(response.content.encode("utf-8")) > 16000:
            raise PlatformError(ErrorCode.BAD_RESPONSE)
        if contains_secret(response.content):
            raise PlatformError(ErrorCode.BAD_RESPONSE, "Sensitive model output was blocked")
        with self.store.edit(data.thread_id, self.actor) as (db, row, current):
            self.store.event(db, row, current, "model.completed", self.provider.last)
        return response

    def route(self, state: DurableState) -> dict[str, object]:
        decision = parse_route_decision(self.generate(state, RouteDecision.model_json_schema()))
        _, profile = self.guard(state)
        if profile.require_evidence and decision.route == "direct":
            decision = RouteDecision(
                route="retrieve", reason="Profile requires evidence", confidence=1
            )
        with self.store.edit(state["thread_id"], self.actor) as (db, row, current):
            self.store.event(
                db,
                row,
                current,
                "route.selected",
                {"route": decision.route, "tool_name": decision.tool_name},
            )
        return {"decision": decision.model_dump(mode="json")}

    def route_edge(
        self, state: DurableState
    ) -> Literal["tool", "retrieve", "respond", "preflight"]:
        decision = RouteDecision.model_validate(state["decision"])
        if decision.route == "tool":
            _, profile = self.guard(state)
            if profile.write_preflight and profile.write_preflight.write_tool == decision.tool_name:
                return "preflight"
            return "tool"
        if decision.route == "retrieve":
            return "retrieve"
        return "respond"

    def retrieve(self, state: DurableState) -> dict[str, object]:
        data, profile = self.guard(state)
        if not profile.knowledge_base_ids:
            raise PlatformError(ErrorCode.PERMISSION)

        def retrieve(remaining: float) -> list[RetrievalHit]:
            token = dependency_timeout.set(remaining)
            try:
                return self.retriever.retrieve_hits(profile.knowledge_base_ids, data.message)
            finally:
                dependency_timeout.reset(token)

        with span("retrieval", profile_id=profile.profile_id):
            hits = retry_call(
                retrieve,
                RetryPolicy(
                    max_attempts=2,
                    total_deadline=min(20, max(0.1, data.deadline_at - self.store.clock())),
                ),
                before_attempt=lambda: self.store.reserve(
                    data.thread_id, state["run_id"], self.actor, "retrieval", retrieval=True
                ),
            ).value
        self.guard(state)
        if any(contains_secret(hit.content) for hit in hits):
            raise PlatformError(ErrorCode.BAD_RESPONSE, "Sensitive source content was blocked")
        pack = build_context_pack(
            hits,
            authorized_knowledge_base_ids=profile.knowledge_base_ids,
            max_content_characters=min(4000, profile.context_policy.max_characters // 2),
        )
        self.fault("after_retrieve")
        if pack.evidence:
            response = self.generate(
                state,
                GroundingProposal.model_json_schema(),
                evidence=render_context_pack_data(pack),
            )
            decision = evaluate_grounding_proposal(
                parse_grounding_proposal(response),
                context_pack=pack,
                authorized_knowledge_base_ids=profile.knowledge_base_ids,
            )
        else:
            decision = decide_grounding_outcome()
        result = runtime_result_from_grounding_decision(
            profile_id=data.profile_id,
            thread_id=data.thread_id,
            decision=decision,
        ).model_dump(mode="json")
        result["retrieval_hits"] = [hit.model_dump(mode="json") for hit in hits]
        result["cache_hit"] = bool(getattr(self.retriever, "last_hit", False))
        return {"result": result}

    def preflight_read(self, state: DurableState) -> dict[str, object]:
        data, profile = self.guard(state)
        proposal = RouteDecision.model_validate(state["decision"])
        configuration = profile.write_preflight
        if configuration is None or proposal.tool_name != configuration.write_tool:
            raise PlatformError(ErrorCode.PERMISSION)
        arguments = proposal.args
        if arguments is None:
            raise PlatformError(ErrorCode.BAD_RESPONSE)
        validate_preflight_configuration(profile, self.registry)
        authorize_tool(self.registry, profile, self.actor, configuration.write_tool, arguments)
        self.current_tool(configuration.write_tool)
        read_arguments = mapped_read_arguments(configuration, arguments)
        definition = authorize_tool(
            self.registry, profile, self.actor, configuration.read_tool, read_arguments
        )
        self.current_tool(configuration.read_tool)
        if data.preflight is not None:
            snapshot = require_preflight(
                profile,
                self.registry,
                data,
                configuration.write_tool,
                arguments,
                store=self.store,
                require_policy=False,
            )
            if snapshot is None:
                raise PlatformError(ErrorCode.CONFLICT)
            return {"preflight": snapshot.model_dump(mode="json")}
        self.store.reserve(data.thread_id, state["run_id"], self.actor, "preflight.read", tool=True)
        timeout_token = dependency_timeout.set(
            min(definition.timeout_seconds, max(0.1, data.deadline_at - self.store.clock()))
        )
        try:
            with span(
                "tool", tool_id=configuration.read_tool, tool_call_id=f"preflight-{data.run_id}"
            ):
                result = self.registry.execute(
                    ToolCall(
                        call_id=f"preflight-{data.run_id}",
                        tool_name=configuration.read_tool,
                        arguments=read_arguments,
                        profile_id=profile.profile_id,
                        thread_id=data.thread_id,
                    ),
                    profile,
                    self.actor.role,
                    False,
                    BudgetPolicy(max_calls=max(1, profile.budgets.max_tool_calls)),
                    calls_used=self.store.load(data.thread_id, self.actor).usage.tool_calls - 1,
                )
        finally:
            dependency_timeout.reset(timeout_token)
        if result.status != "succeeded" or not isinstance(result.data, dict):
            raise PlatformError(ErrorCode.BAD_RESPONSE, "Preflight record lookup did not succeed")
        serialized = json.dumps(result.data, ensure_ascii=False)
        if len(serialized.encode()) > 16000 or contains_secret(serialized):
            raise PlatformError(ErrorCode.BAD_RESPONSE, "Preflight record response was blocked")
        safe_result = redact(result.data)
        if not isinstance(safe_result, dict) or any(
            safe_result.get(key) != value for key, value in read_arguments.items()
        ):
            raise PlatformError(ErrorCode.BAD_RESPONSE, "Preflight record identity does not match")
        snapshot = PreflightSnapshot(
            run_id=state["run_id"],
            profile_version=profile.version,
            configuration_hash=digest(configuration.model_dump(mode="json")),
            write_tool=configuration.write_tool,
            read_tool=configuration.read_tool,
            read_policy_hash=policy_hash(definition),
            read_arguments=read_arguments,
            read_result=safe_result,
        )
        with self.store.edit(data.thread_id, self.actor) as (db, row, current):
            if current.status == "cancelled":
                raise PlatformError(ErrorCode.CANCELLED)
            current.preflight = snapshot
            self.store.event(
                db, row, current, "preflight.read_completed", {"tool_name": definition.name}
            )
            self.store.audit(
                db, current, "preflight.read_completed", result_hash=digest(safe_result)
            )
        self.fault("after_preflight_read")
        return {"preflight": snapshot.model_dump(mode="json")}

    def preflight_policy(self, state: DurableState) -> dict[str, object]:
        data, profile = self.guard(state)
        proposal = RouteDecision.model_validate(state["decision"])
        configuration = profile.write_preflight
        if (
            configuration is None
            or proposal.tool_name != configuration.write_tool
            or proposal.args is None
        ):
            raise PlatformError(ErrorCode.PERMISSION)
        snapshot = require_preflight(
            profile,
            self.registry,
            data,
            configuration.write_tool,
            proposal.args,
            store=self.store,
            require_policy=False,
        )
        if snapshot is None:
            raise PlatformError(ErrorCode.CONFLICT)
        if snapshot.policy_context is None:
            self.store.reserve(
                data.thread_id, state["run_id"], self.actor, "preflight.policy", retrieval=True
            )
            timeout_token = dependency_timeout.set(
                min(20, max(0.1, data.deadline_at - self.store.clock()))
            )
            try:
                with span("retrieval", profile_id=profile.profile_id):
                    hits = self.retriever.retrieve_hits(
                        profile.knowledge_base_ids, configuration.policy_query
                    )
            finally:
                dependency_timeout.reset(timeout_token)
            pack = build_context_pack(
                hits,
                authorized_knowledge_base_ids=profile.knowledge_base_ids,
                max_content_characters=min(4000, profile.context_policy.max_characters // 2),
            )
            if not pack.evidence or any(contains_secret(item.content) for item in pack.evidence):
                raise PlatformError(
                    ErrorCode.BAD_RESPONSE, "Preflight policy evidence is unavailable"
                )
            with self.store.factory() as database:
                revisions = policy_revisions(database, pack)
            snapshot = snapshot.model_copy(
                update={"policy_context": pack, "policy_revisions": revisions}
            )
            with self.store.edit(data.thread_id, self.actor) as (db, row, current):
                if current.status == "cancelled":
                    raise PlatformError(ErrorCode.CANCELLED)
                current.preflight = snapshot
                self.store.event(
                    db,
                    row,
                    current,
                    "preflight.policy_completed",
                    {"evidence_count": len(pack.evidence)},
                )
                self.store.audit(
                    db,
                    current,
                    "preflight.policy_completed",
                    evidence_hash=digest(pack.model_dump(mode="json")),
                )
        self.fault("after_preflight_policy")
        return {"preflight": snapshot.model_dump(mode="json")}

    def propose(self, state: DurableState) -> dict[str, object]:
        data, profile = self.guard(state)
        proposal = RouteDecision.model_validate(state["decision"])
        name, arguments = proposal.tool_name, proposal.args
        if name is None or arguments is None:
            raise PlatformError(ErrorCode.BAD_RESPONSE)
        definition = authorize_tool(self.registry, profile, self.actor, name, arguments)
        require_preflight(profile, self.registry, data, name, arguments, store=self.store)
        self.current_tool(name)
        self.store.reserve(data.thread_id, state["run_id"], self.actor, "proposal")
        if needs_approval(definition, profile):
            return {"approval_id": self.approvals.propose(data, self.actor, name, arguments)}
        with self.store.edit(data.thread_id, self.actor) as (db, row, current):
            self.store.event(
                db, row, current, "tool.proposed", {"tool_name": name, "arguments": arguments}
            )
        return {"approval_id": None}

    def proposal_edge(self, state: DurableState) -> Literal["approval", "execute"]:
        return "approval" if state["approval_id"] else "execute"

    def approval(self, state: DurableState) -> dict[str, object]:
        self.guard(state)
        approval_id = state["approval_id"]
        if approval_id is None:
            raise PlatformError(ErrorCode.PERMISSION)
        row = self.approvals.get(state["thread_id"], approval_id, self.actor)
        if row["status"] == "pending":
            interrupt({"approval_id": approval_id})
        # The resume value carries no authority. The execution node rereads the database.
        return {}

    def execute(self, state: DurableState) -> dict[str, object]:
        data, profile = self.guard(state)
        proposal = RouteDecision.model_validate(state["decision"])
        name, arguments = proposal.tool_name, proposal.args
        if name is None or arguments is None:
            raise PlatformError(ErrorCode.BAD_RESPONSE)
        approval_id = state["approval_id"]
        approval_granted = False
        if approval_id:
            with self.store.factory() as db:
                row = db.get(ApprovalRow, approval_id)
                if (
                    row is None
                    or row.thread_id != data.thread_id
                    or row.run_id != data.run_id
                    or row.user_id != self.actor.user_id
                    or row.tool_name != name
                ):
                    raise PlatformError(ErrorCode.PERMISSION)
                arguments = row.arguments
                definition = authorize_tool(self.registry, profile, self.actor, name, arguments)
                if (
                    row.policy_hash != policy_hash(definition)
                    or row.profile_version != profile.version
                ):
                    raise PlatformError(ErrorCode.CONFLICT, "Approval policy changed")
                if row.status in ("executed", "failed") and row.result is not None:
                    return {"result": row.result}
                if row.status in ("rejected", "expired"):
                    return {
                        "result": {
                            "status": "rejected",
                            "route": "tool",
                            "output_text": "Tool was not executed.",
                            "error": row.status,
                        }
                    }
                if row.status != "approved" or not row.decision_key:
                    raise PlatformError(ErrorCode.PERMISSION)
                if row.expires_at.timestamp() <= self.store.clock():
                    raise PlatformError(ErrorCode.EXPIRED)
                approval_granted = True
        definition = authorize_tool(self.registry, profile, self.actor, name, arguments)
        preflight = require_preflight(
            profile, self.registry, data, name, arguments, store=self.store
        )
        if needs_approval(definition, profile) and not approval_granted:
            raise PlatformError(ErrorCode.PERMISSION)
        key = approval_id or f"read-{data.run_id}"
        token = execution_key.set(key)

        def attempt(remaining: float) -> ToolResult:
            current_data, current_profile = self.guard(state)
            self.current_tool(name)
            authorize_tool(self.registry, current_profile, self.actor, name, arguments)
            require_preflight(
                current_profile, self.registry, current_data, name, arguments, store=self.store
            )
            self.store.reserve(data.thread_id, state["run_id"], self.actor, "tool", tool=True)
            timeout_token = dependency_timeout.set(
                min(
                    remaining,
                    definition.timeout_seconds,
                    max(0.1, data.deadline_at - self.store.clock()),
                )
            )
            try:
                with span("tool", tool_id=name, tool_call_id=key, approval_id=approval_id or ""):
                    value = self.registry.execute(
                        ToolCall(
                            call_id=key,
                            tool_name=name,
                            arguments=arguments,
                            profile_id=profile.profile_id,
                            thread_id=data.thread_id,
                        ),
                        profile,
                        self.actor.role,
                        approval_granted,
                        BudgetPolicy(max_calls=max(1, profile.budgets.max_tool_calls)),
                        calls_used=self.store.load(data.thread_id, self.actor).usage.tool_calls - 1,
                    )
                    if value.error:
                        failure = ToolBusinessError(value.error.code, value.error.message)
                        if transient(failure):
                            raise failure
                    return value
            finally:
                dependency_timeout.reset(timeout_token)

        try:
            self.fault("before_tool")
            result = retry_call(
                attempt,
                RetryPolicy(
                    max_attempts=2,
                    total_deadline=min(30, max(0.1, data.deadline_at - self.store.clock())),
                ),
                write=definition.effect == "write",
                idempotency_key=approval_id,
            ).value
        finally:
            execution_key.reset(token)
        self.fault("after_tool")
        serialized = result.model_dump(mode="json")
        if len(json.dumps(serialized).encode()) > 16000:
            raise PlatformError(ErrorCode.BAD_RESPONSE)
        if result.error and result.error.code == "tool_timeout":
            raise PlatformError(ErrorCode.TIMEOUT)
        safe_data = redact(result.data)
        serialized["data"] = safe_data
        output: dict[str, object] = {
            "status": result.status,
            "route": "tool",
            "tool_name": name,
            "arguments": arguments,
            "tool_result": serialized,
            "output_text": json.dumps(safe_data, ensure_ascii=False)
            if result.data is not None
            else "Tool could not complete the request.",
        }
        if preflight is not None:
            output["preflight"] = preflight.model_dump(mode="json")
        with self.store.edit(data.thread_id, self.actor) as (db, session_row, current):
            if approval_id:
                row = db.get(ApprovalRow, approval_id)
                if row is None:
                    raise PlatformError(ErrorCode.PERMISSION)
                row.status = "executed" if result.status == "succeeded" else "failed"
                row.result = output
                row.version += 1
            self.store.event(db, session_row, current, "tool.result", output)
            self.store.audit(db, current, "tool.finished", tool=name, status=result.status)
        return {"result": output}

    def respond(self, state: DurableState) -> dict[str, object]:
        data, _ = self.guard(state)
        self.store.reserve(data.thread_id, state["run_id"], self.actor, "respond")
        result = state["result"]
        if result is None:
            proposal = RouteDecision.model_validate(state["decision"])
            result = {
                "status": "succeeded",
                "route": proposal.route,
                "output_text": proposal.output_text or "Please clarify your request.",
            }
        self.fault("before_respond")
        with self.store.factory() as db:
            models = list(
                db.scalars(
                    select(EventRow)
                    .where(
                        EventRow.thread_id == data.thread_id,
                        EventRow.run_id == data.run_id,
                        EventRow.kind == "model.completed",
                    )
                    .order_by(EventRow.sequence)
                )
            )
        result = {
            **result,
            "model_calls": [row.data for row in models],
            "degraded": any(row.data.get("degraded") for row in models),
        }
        self.store.finish(data.thread_id, self.actor, result)
        return {"result": result}

    def invoke(self, data: SessionData, *, fresh: bool = False) -> SessionData:
        if data.run_id is None:
            raise PlatformError(ErrorCode.CONFLICT)
        if data.status == "failed":
            with self.store.edit(data.thread_id, self.actor) as (_, _, current):
                if current.status == "cancelled":
                    return current
                current.status = "running"
                current.error = None
        config = self.config(data.thread_id)
        initial: DurableState = {
            "schema_version": 1,
            "thread_id": data.thread_id,
            "run_id": data.run_id,
            "decision": None,
            "result": None,
            "approval_id": None,
            "preflight": None,
        }
        try:
            if fresh:
                self.graph.invoke(initial, config, durability="sync")
            else:
                snapshot = self.graph.get_state(config)
                if snapshot.values.get("schema_version") != 1:
                    raise PlatformError(ErrorCode.SCHEMA)
                if snapshot.values.get("run_id") != data.run_id:
                    raise PlatformError(ErrorCode.CONFLICT)
                if any(task.interrupts for task in snapshot.tasks):
                    self.graph.invoke(Command(resume="server-decision"), config, durability="sync")
                else:
                    self.graph.invoke(None, config, durability="sync")
        except PlatformError as exc:
            return self.store.fail(data.thread_id, self.actor, exc.code.value)
        except ValidationError:
            return self.store.fail(data.thread_id, self.actor, ErrorCode.BAD_RESPONSE.value)
        except Exception as exc:
            return self.store.fail(data.thread_id, self.actor, error_code(exc).value)
        return self.store.load(data.thread_id, self.actor)

    def send(self, thread_id: str, message: str, request_key: str) -> SessionData:
        with self.store.lock(thread_id):
            data = self.store.begin(thread_id, self.actor, message, request_key)
            if data.status in ("completed", "awaiting_approval"):
                return data
            snapshot = self.graph.get_state(self.config(thread_id))
            return self.invoke(data, fresh=snapshot.values.get("run_id") != data.run_id)

    def resume(self, thread_id: str) -> SessionData:
        with self.store.lock(thread_id):
            data = self.store.load(thread_id, self.actor)
            if data.status == "completed":
                return data
            if data.run_id is None:
                raise PlatformError(ErrorCode.CONFLICT)
            self.store.guard(thread_id, data.run_id, self.actor)
            if data.approval_id:
                approval = self.approvals.get(thread_id, data.approval_id, self.actor)
                if approval["status"] == "pending":
                    return data
            return self.invoke(data)

    def decide(self, thread_id: str, approval_id: str, decision: ApprovalDecision) -> SessionData:
        with (
            self.store.lock(thread_id),
            correlation(thread_id=thread_id, approval_id=approval_id),
            span("approval", approval_id=approval_id),
        ):
            self.approvals.decide(thread_id, approval_id, self.actor, decision)
            data = self.store.load(thread_id, self.actor)
            return data if data.status == "completed" else self.invoke(data)

    def cancel(self, thread_id: str) -> SessionData:
        # The short row transaction must not wait on the graph's advisory lock.
        # An already dispatched external effect may finish; later nodes stop at guards.
        self.store.load_authorized(thread_id, self.actor)
        with self.store.edit(thread_id, self.actor) as (db, row, data):
            if data.status in ("cancelled", "completed"):
                return data
            data.status = "cancelled"
            for approval in db.scalars(
                select(ApprovalRow).where(
                    ApprovalRow.thread_id == thread_id,
                    ApprovalRow.status == "pending",
                )
            ):
                approval.status = "rejected"
                approval.version += 1
            self.store.event(
                db, row, data, "run.cancelled", {"external_effect_may_be_in_flight": True}
            )
            self.store.audit(db, data, "session.cancelled")
        return data

    def delete(self, thread_id: str) -> None:
        with self.store.lock(thread_id):
            # Deletion is permitted after expiry; ownership is still mandatory.
            with self.store.factory.begin() as db:
                row = db.get(SessionRow, thread_id)
                if row is None or row.user_id != self.actor.user_id:
                    raise PlatformError(ErrorCode.NOT_FOUND)
                self.saver.delete_thread(thread_id)
                db.execute(delete(SessionRow).where(SessionRow.thread_id == thread_id))

    def purge_expired(self) -> int:
        with self.store.factory() as db:
            rows = list(
                db.scalars(select(SessionRow).where(SessionRow.user_id == self.actor.user_id))
            )
            expired = [
                row.thread_id for row in rows if row.expires_at.timestamp() <= self.store.clock()
            ]
        for thread_id in expired:
            self.delete(thread_id)
        return len(expired)
