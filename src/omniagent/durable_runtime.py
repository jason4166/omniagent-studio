"""One durable graph for every profile; policy and effects remain server-owned."""

import json
from collections.abc import Callable
from typing import Literal, TypedDict

from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt
from pydantic import ValidationError
from sqlalchemy import delete, select

from omniagent.approvals import ApprovalService, authorize_tool, needs_approval, policy_hash
from omniagent.context import build_context
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
from omniagent.postgres_repositories import SqlAlchemyPromptVersionRepository
from omniagent.profiles import AgentProfile
from omniagent.runtime import runtime_result_from_grounding_decision
from omniagent.session_models import ApprovalDecision, SessionData
from omniagent.session_rows import ApprovalRow, SessionRow
from omniagent.session_store import SessionStore
from omniagent.tool_registry import ToolRegistry
from omniagent.tooling import BudgetPolicy, ToolCall


class DurableState(TypedDict):
    schema_version: int
    thread_id: str
    run_id: str
    decision: dict[str, object] | None
    result: dict[str, object] | None
    approval_id: str | None


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
    ) -> None:
        self.store = store
        self.saver = saver
        self.actor = actor
        self.provider = provider
        self.registry = registry
        self.retriever = retriever
        self.approvals = ApprovalService(store, registry)
        self.failure_hook = failure_hook
        builder = StateGraph(DurableState)
        builder.add_node("route", self.route)
        builder.add_node("retrieve", self.retrieve)
        builder.add_node("propose", self.propose)
        builder.add_node("approval", self.approval)
        builder.add_node("execute", self.execute)
        builder.add_node("respond", self.respond)
        builder.add_edge(START, "route")
        builder.add_conditional_edges(
            "route",
            self.route_edge,
            {
                "tool": "propose",
                "retrieve": "retrieve",
                "respond": "respond",
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
        builder.add_edge("execute", "respond")
        builder.add_edge("retrieve", "respond")
        builder.add_edge("respond", END)
        self.graph = builder.compile(checkpointer=saver)

    def config(self, thread_id: str) -> RunnableConfig:
        return {"configurable": {"thread_id": thread_id}, "recursion_limit": 12}

    def guard(self, state: DurableState) -> tuple[SessionData, AgentProfile]:
        if state.get("schema_version") != 1:
            raise PlatformError(ErrorCode.SCHEMA)
        return self.store.guard(state["thread_id"], state["run_id"], self.actor)

    def fault(self, boundary: str) -> None:
        if self.failure_hook is not None:
            self.failure_hook(boundary)

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
        instruction = prompt.content + ("\n" + GROUNDING_RESPONSE_INSTRUCTION if evidence else "")
        context = build_context(
            instruction, data.history, data.message, profile.context_policy, evidence_data=evidence
        )
        self.store.reserve(
            data.thread_id,
            state["run_id"],
            self.actor,
            "llm",
            tokens=context.estimated_tokens + 1024,
            model=True,
        )
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
        if len(response.content.encode("utf-8")) > 16000:
            raise PlatformError(ErrorCode.BAD_RESPONSE)
        self.store.record_usage(
            data.thread_id, self.actor, response.usage, fake=profile.provider_id == "fake"
        )
        return response

    def route(self, state: DurableState) -> dict[str, object]:
        decision = parse_route_decision(self.generate(state, RouteDecision.model_json_schema()))
        _, profile = self.guard(state)
        if profile.require_evidence and decision.route == "direct":
            decision = RouteDecision(
                route="retrieve", reason="Profile requires evidence", confidence=1
            )
        return {"decision": decision.model_dump(mode="json")}

    def route_edge(self, state: DurableState) -> Literal["tool", "retrieve", "respond"]:
        decision = RouteDecision.model_validate(state["decision"])
        if decision.route == "tool":
            return "tool"
        if decision.route == "retrieve":
            return "retrieve"
        return "respond"

    def retrieve(self, state: DurableState) -> dict[str, object]:
        data, profile = self.guard(state)
        if not profile.knowledge_base_ids:
            raise PlatformError(ErrorCode.PERMISSION)
        self.store.reserve(data.thread_id, state["run_id"], self.actor, "retrieval", retrieval=True)
        hits = self.retriever.retrieve_hits(profile.knowledge_base_ids, data.message)
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
        return {"result": result}

    def propose(self, state: DurableState) -> dict[str, object]:
        data, profile = self.guard(state)
        proposal = RouteDecision.model_validate(state["decision"])
        name, arguments = proposal.tool_name, proposal.args
        if name is None or arguments is None:
            raise PlatformError(ErrorCode.BAD_RESPONSE)
        definition = authorize_tool(self.registry, profile, self.actor, name, arguments)
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
        if needs_approval(definition, profile) and not approval_granted:
            raise PlatformError(ErrorCode.PERMISSION)
        self.store.reserve(data.thread_id, state["run_id"], self.actor, "tool", tool=True)
        key = approval_id or f"read-{data.run_id}"
        token = execution_key.set(key)
        try:
            self.fault("before_tool")
            result = self.registry.execute(
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
                calls_used=data.usage.tool_calls,
            )
        finally:
            execution_key.reset(token)
        self.fault("after_tool")
        serialized = result.model_dump(mode="json")
        if len(json.dumps(serialized).encode()) > 16000:
            raise PlatformError(ErrorCode.BAD_RESPONSE)
        if result.error and result.error.code == "tool_timeout":
            raise PlatformError(ErrorCode.TIMEOUT)
        output: dict[str, object] = {
            "status": result.status,
            "route": "tool",
            "tool_name": name,
            "arguments": arguments,
            "tool_result": serialized,
            "output_text": json.dumps(result.data, ensure_ascii=False)
            if result.data is not None
            else "Tool could not complete the request.",
        }
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
        self.store.finish(data.thread_id, self.actor, result)
        return {"result": result}

    def invoke(self, data: SessionData, *, fresh: bool = False) -> SessionData:
        if data.run_id is None:
            raise PlatformError(ErrorCode.CONFLICT)
        if data.status == "failed":
            with self.store.edit(data.thread_id, self.actor) as (_, _, current):
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
        except Exception:
            return self.store.fail(data.thread_id, self.actor, ErrorCode.UNAVAILABLE.value)
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
        with self.store.lock(thread_id):
            self.approvals.decide(thread_id, approval_id, self.actor, decision)
            data = self.store.load(thread_id, self.actor)
            return data if data.status == "completed" else self.invoke(data)

    def cancel(self, thread_id: str) -> SessionData:
        with self.store.lock(thread_id), self.store.edit(thread_id, self.actor) as (db, row, data):
            data.status = "cancelled"
            for approval in db.scalars(
                select(ApprovalRow).where(
                    ApprovalRow.thread_id == thread_id,
                    ApprovalRow.status.in_(("pending", "approved")),
                )
            ):
                approval.status = "rejected"
                approval.version += 1
            self.store.event(db, row, data, "run.cancelled", {})
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
