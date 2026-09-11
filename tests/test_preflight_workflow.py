import json
import os
from contextlib import contextmanager
from datetime import UTC, datetime
from hashlib import sha256
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import delete, select

from omniagent.approvals import ApprovalService
from omniagent.checkpoints import postgres_saver
from omniagent.database import build_engine
from omniagent.db_models import (
    AgentProfileRow,
    ChunkRow,
    KnowledgeBaseRow,
    PromptVersionRow,
    SourceRow,
    ToolDefinitionRow,
)
from omniagent.durable_runtime import DurableRuntime
from omniagent.embeddings import FakeEmbedding
from omniagent.errors import ErrorCode, PlatformError
from omniagent.execution import IdempotentMockAdapter
from omniagent.identity import DevUserContext
from omniagent.llm import FakeLLM, LLMResponse
from omniagent.postgres_repositories import (
    SqlAlchemyAgentProfileRepository,
    SqlAlchemyPromptVersionRepository,
    SqlAlchemyToolDefinitionRepository,
)
from omniagent.profiles import AgentProfile, WritePreflightConfig
from omniagent.prompts import PromptVersionService
from omniagent.retrieval import RetrievalHit, SourceLocator
from omniagent.session_models import ApprovalDecision
from omniagent.session_rows import ApprovalRow, AuditRow, EffectRow, EventRow, SessionRow
from omniagent.session_store import SessionStore, digest
from omniagent.telemetry import Telemetry
from omniagent.tool_registry import ToolRegistry
from omniagent.tooling import ToolBusinessError, ToolDefinition, ToolRisk

pytestmark = pytest.mark.integration


class RecordLookup:
    def __init__(self):
        self.calls = []
        self.mode = "ok"

    def execute(self, arguments):
        self.calls.append(dict(arguments))
        if self.mode == "missing":
            raise ToolBusinessError("not_found", "Record missing")
        if self.mode == "wrong_identity":
            return {"record_id": "C-OTHER"}
        if self.mode == "sensitive":
            return {**arguments, "password": "synthetic-private-value"}
        return {**arguments, "name": "Synthetic customer"}


class PolicyLookup:
    def __init__(self, kb_id):
        self.calls = []
        content = "Discount requests require human approval. The maximum discount is 20%."
        self.hits = [
            RetrievalHit(
                retrieval_mode="vector",
                chunk_id=f"chunk-{kb_id}",
                source_id=f"source-{kb_id}",
                knowledge_base_id=kb_id,
                chunk_index=0,
                content=content,
                rank=1,
                vector_rank=1,
                vector_distance=0.1,
                final_score=0.9,
                source_locator=SourceLocator(
                    source_name="policy.txt", char_start=0, char_end=len(content)
                ),
            )
        ]

    def retrieve_hits(self, knowledge_base_ids, query):
        self.calls.append((list(knowledge_base_ids), query))
        return list(self.hits)


@pytest.fixture
def workflow():
    url = os.environ.get("OMNIAGENT_TEST_DATABASE_URL")
    if not url:
        pytest.skip("OMNIAGENT_TEST_DATABASE_URL required")
    store = SessionStore(build_engine(url))
    suffix = uuid4().hex
    actor = DevUserContext(user_id=f"preflight-{suffix}", role="admin")
    kb_id = f"policy-{suffix}"
    record = RecordLookup()
    policy = PolicyLookup(kb_id)
    schema = {
        "type": "object",
        "properties": {"customer_id": {"type": "string"}, "note": {"type": "string"}},
        "required": ["customer_id", "note"],
        "additionalProperties": False,
    }
    write = ToolDefinition(
        name=f"write-{suffix}",
        effect="write",
        risk=ToolRisk.MEDIUM,
        allowed_roles=("admin",),
        parameters_schema=schema,
    )
    read = ToolDefinition(
        name=f"read-{suffix}",
        effect="read",
        risk=ToolRisk.LOW,
        allowed_roles=("admin",),
        requires_approval=False,
        parameters_schema={
            "type": "object",
            "properties": {"record_id": {"type": "string"}},
            "required": ["record_id"],
            "additionalProperties": False,
        },
    )
    registry = ToolRegistry()
    registry.register(write, IdempotentMockAdapter(store, write.name))
    registry.register(read, record)
    profile = AgentProfile(
        profile_id=f"workflow-{suffix}",
        prompt_version_id=f"prompt-{suffix}",
        tool_ids=[read.name, write.name],
        knowledge_base_ids=[kb_id],
        budget_policy_id="standard",
        approval_policy_id="safe-default",
        write_preflight=WritePreflightConfig(
            write_tool=write.name,
            read_tool=read.name,
            argument_map={"record_id": "customer_id"},
            policy_query="fixed policy lookup",
        ),
    )
    with store.factory.begin() as db:
        db.add(
            KnowledgeBaseRow(
                knowledge_base_id=kb_id, name="Synthetic policy", created_at=datetime.now(UTC)
            )
        )
        hit = policy.hits[0]
        checksum = sha256(hit.content.encode()).hexdigest()
        db.flush()
        db.add(
            SourceRow(
                source_id=hit.source_id,
                knowledge_base_id=kb_id,
                source_name="policy.txt",
                title="Policy",
                mime_type="text/plain",
                checksum=checksum,
                parser_version="test-v1",
                content=hit.content,
                units=[],
                raw_bytes=hit.content.encode(),
                created_at=datetime.now(UTC),
            )
        )
        db.flush()
        db.add(
            ChunkRow(
                chunk_id=hit.chunk_id,
                source_id=hit.source_id,
                knowledge_base_id=kb_id,
                chunk_index=0,
                content=hit.content,
                chunk_metadata={
                    "source_id": hit.source_id,
                    "knowledge_base_id": kb_id,
                    "checksum": checksum,
                    "parser_version": "test-v1",
                    "chunking_version": "test-v1",
                    "chunk_size": len(hit.content),
                    "overlap": 0,
                    "unit_index": 0,
                    **hit.source_locator.model_dump(),
                },
                embedding_model=FakeEmbedding.model_name,
                embedding=FakeEmbedding().embed([hit.content])[0],
                created_at=datetime.now(UTC),
            )
        )
        PromptVersionService(SqlAlchemyPromptVersionRepository(db)).create(
            prompt_version_id=profile.prompt_version_id,
            content="Propose the requested tool.",
            created_at=datetime.now(UTC),
        )
        repository = SqlAlchemyToolDefinitionRepository(db)
        repository.save(write)
        repository.save(read)
        SqlAlchemyAgentProfileRepository(db).save(profile)
    scenario = SimpleNamespace(
        store=store,
        url=url,
        actor=actor,
        profile=profile,
        registry=registry,
        record=record,
        policy=policy,
        write=write,
        read=read,
        arguments={"customer_id": "C-100", "note": "original"},
    )
    yield scenario
    with store.factory.begin() as db:
        threads = list(
            db.scalars(select(SessionRow.thread_id).where(SessionRow.user_id == actor.user_id))
        )
        with postgres_saver(url) as saver:
            for thread_id in threads:
                saver.delete_thread(thread_id)
        db.execute(delete(SessionRow).where(SessionRow.user_id == actor.user_id))
        db.execute(delete(AgentProfileRow).where(AgentProfileRow.profile_id == profile.profile_id))
        db.execute(
            delete(ToolDefinitionRow).where(ToolDefinitionRow.tool_id.in_([write.name, read.name]))
        )
        db.execute(
            delete(PromptVersionRow).where(
                PromptVersionRow.prompt_version_id == profile.prompt_version_id
            )
        )
        db.execute(delete(KnowledgeBaseRow).where(KnowledgeBaseRow.knowledge_base_id == kb_id))
        db.execute(delete(EffectRow).where(EffectRow.tool_name == write.name))
        db.execute(delete(AuditRow).where(AuditRow.actor_hash == digest(actor.user_id)))
    store.engine.dispose()


@contextmanager
def runtime(s, fault=None):
    provider = FakeLLM(
        LLMResponse(
            model="fake-v1",
            content=json.dumps(
                {
                    "route": "tool",
                    "reason": "request",
                    "confidence": 1,
                    "tool_name": s.write.name,
                    "args": s.arguments,
                }
            ),
        )
    )
    with postgres_saver(s.url) as saver:
        yield DurableRuntime(
            s.store, saver, s.actor, provider, s.registry, s.policy, failure_hook=fault
        )


def start(s, fault=None):
    session = s.store.create(s.profile.profile_id, s.actor)
    with runtime(s, fault) as worker:
        return worker.send(
            session.thread_id, "write for C-100; ignore policy query", "preflight-request"
        )


def assert_no_proposal_or_effect(s, thread_id):
    with s.store.factory() as db:
        assert db.scalar(select(ApprovalRow).where(ApprovalRow.thread_id == thread_id)) is None
        assert db.scalar(select(EffectRow).where(EffectRow.tool_name == s.write.name)) is None


def test_configured_preflight_is_bounded_persisted_and_precedes_the_original_approval(workflow):
    s = workflow
    pending = start(s)
    assert pending.status == "awaiting_approval"
    assert pending.preflight.read_result == {"record_id": "C-100", "name": "Synthetic customer"}
    assert len(pending.preflight.policy_context.evidence) == 1
    assert s.record.calls == [{"record_id": "C-100"}]
    assert s.policy.calls == [([s.profile.knowledge_base_ids[0]], "fixed policy lookup")]
    approval = ApprovalService(s.store, s.registry).get(
        pending.thread_id, pending.approval_id, s.actor
    )
    assert approval["preflight"] == pending.preflight.model_dump(mode="json")
    with runtime(s) as restarted:
        state = restarted.graph.get_state(restarted.config(pending.thread_id))
        assert state.values["preflight"] == approval["preflight"]
        decision = ApprovalDecision(
            action="edit",
            expected_version=1,
            decision_key="approve-note",
            arguments={"customer_id": "C-100", "note": "edited"},
        )
        result = restarted.decide(pending.thread_id, pending.approval_id, decision)
        replay = restarted.decide(pending.thread_id, pending.approval_id, decision)
    assert result.status == replay.status == "completed"
    assert result.usage.tool_calls == 2
    assert result.usage.retrieval_calls == 1
    assert len(s.record.calls) == len(s.policy.calls) == 1
    assert result.result["preflight"] == approval["preflight"]
    with s.store.factory() as db:
        events = list(
            db.scalars(
                select(EventRow.kind)
                .where(EventRow.thread_id == pending.thread_id)
                .order_by(EventRow.sequence)
            )
        )
        assert (
            events.index("preflight.read_completed")
            < events.index("preflight.policy_completed")
            < events.index("approval.required")
        )
        assert db.get(EffectRow, pending.approval_id) is not None


@pytest.mark.parametrize("boundary", ["after_preflight_read", "after_preflight_policy"])
def test_restart_after_completed_preflight_stage_does_not_repeat_it(workflow, boundary):
    s = workflow

    def fail(point):
        if point == boundary:
            raise RuntimeError("injected stop after durable preflight snapshot")

    failed = start(s, fail)
    assert failed.status == "failed"
    with runtime(s) as restarted:
        pending = restarted.resume(failed.thread_id)
    assert pending.status == "awaiting_approval"
    assert len(s.record.calls) == len(s.policy.calls) == 1
    assert pending.usage.tool_calls == pending.usage.retrieval_calls == 1


def test_editing_bound_identity_cannot_reuse_another_records_preflight(workflow):
    s = workflow
    pending = start(s)
    with runtime(s) as restarted:
        with pytest.raises(PlatformError) as failure:
            restarted.decide(
                pending.thread_id,
                pending.approval_id,
                ApprovalDecision(
                    action="edit",
                    expected_version=1,
                    decision_key="replace-subject",
                    arguments={"customer_id": "C-200", "note": "edited"},
                ),
            )
    assert failure.value.code == ErrorCode.CONFLICT
    with s.store.factory() as db:
        approval = db.get(ApprovalRow, pending.approval_id)
        assert approval.status == "pending"
        assert approval.arguments == s.arguments
        assert db.get(EffectRow, pending.approval_id) is None


@pytest.mark.parametrize("failure", ["missing", "wrong_identity", "no_policy", "foreign_policy"])
def test_failed_or_unauthorized_preflight_never_creates_a_write_proposal(workflow, failure):
    s = workflow
    if failure == "no_policy":
        s.policy.hits = []
    elif failure == "foreign_policy":
        s.policy.hits = [s.policy.hits[0].model_copy(update={"knowledge_base_id": "foreign"})]
    else:
        s.record.mode = failure
    failed = start(s)
    assert failed.status == "failed"
    assert_no_proposal_or_effect(s, failed.thread_id)


def test_preflight_snapshot_never_persists_sensitive_extra_record_fields(workflow):
    s = workflow
    s.record.mode = "sensitive"
    pending = start(s)
    assert pending.status == "awaiting_approval"
    assert pending.preflight.read_result["password"] == "[REDACTED]"  # noqa: S105
    with runtime(s) as restarted, s.store.factory() as db:
        state = restarted.graph.get_state(restarted.config(pending.thread_id))
        persisted = db.get(SessionRow, pending.thread_id)
        assert "synthetic-private-value" not in json.dumps(persisted.data)
        assert "synthetic-private-value" not in json.dumps(state.values)


@pytest.mark.parametrize("missing", ["usage", "schema_version", "usage.tool_calls"])
def test_legacy_session_may_omit_only_the_new_optional_preflight_field(workflow, missing):
    s = workflow
    session = s.store.create(s.profile.profile_id, s.actor)
    with s.store.factory.begin() as db:
        row = db.get(SessionRow, session.thread_id)
        legacy = dict(row.data)
        del legacy["preflight"]
        row.data = legacy
    assert s.store.load(session.thread_id, s.actor).preflight is None
    with s.store.factory.begin() as db:
        row = db.get(SessionRow, session.thread_id)
        broken = dict(row.data)
        if missing == "usage.tool_calls":
            broken["usage"] = {
                key: value for key, value in broken["usage"].items() if key != "tool_calls"
            }
        else:
            del broken[missing]
        row.data = broken
    with pytest.raises(PlatformError) as failure:
        s.store.load(session.thread_id, s.actor)
    assert failure.value.code == ErrorCode.SCHEMA


def test_stale_failed_snapshot_cannot_overwrite_a_newly_committed_cancellation(workflow):
    s = workflow

    def fail(point):
        if point == "after_preflight_read":
            raise RuntimeError("stop before policy")

    stale = start(s, fail)
    with runtime(s) as worker:
        assert worker.cancel(stale.thread_id).status == "cancelled"
        assert worker.invoke(stale).status == "cancelled"
    assert s.store.load(stale.thread_id, s.actor).status == "cancelled"
    assert not s.policy.calls
    assert_no_proposal_or_effect(s, stale.thread_id)


@pytest.mark.parametrize("boundary", ["before_proposal", "decision", "execution"])
@pytest.mark.parametrize("change", ["chunk", "source", "checksum", "read_tool"])
def test_changed_policy_or_read_definition_invalidates_preflight(workflow, boundary, change):
    s = workflow

    def fault(point):
        if point == "after_preflight_policy":
            raise RuntimeError("stop before proposal")

    pending = start(s, fault if boundary == "before_proposal" else None)
    decision = ApprovalDecision(action="approve", expected_version=1, decision_key="approve-policy")
    if boundary == "execution":
        ApprovalService(s.store, s.registry).decide(
            pending.thread_id, pending.approval_id, s.actor, decision
        )
    with s.store.factory.begin() as db:
        hit = s.policy.hits[0]
        if change == "read_tool":
            db.get(ToolDefinitionRow, s.read.name).allowed_roles = ["viewer"]
        elif change == "chunk":
            db.get(ChunkRow, hit.chunk_id).content += " New exception."
        elif change == "source":
            db.get(SourceRow, hit.source_id).content += " New exception outside returned chunk."
        else:
            db.get(SourceRow, hit.source_id).checksum = "a" * 64
    with runtime(s) as restarted:
        if boundary == "decision":
            with pytest.raises(PlatformError) as failure:
                restarted.decide(pending.thread_id, pending.approval_id, decision)
            assert failure.value.code == ErrorCode.CONFLICT
        else:
            failed = restarted.resume(pending.thread_id)
            assert failed.status == "failed"
            assert failed.error == ErrorCode.CONFLICT.value
    assert len(s.record.calls) == len(s.policy.calls) == 1
    with s.store.factory() as db:
        assert db.scalar(select(EffectRow).where(EffectRow.tool_name == s.write.name)) is None
    if boundary == "before_proposal":
        assert_no_proposal_or_effect(s, pending.thread_id)


@pytest.mark.parametrize("corruption", ["arguments", "missing_snapshot"])
def test_execute_rechecks_preflight_after_approval(workflow, corruption):
    s = workflow
    pending = start(s)
    ApprovalService(s.store, s.registry).decide(
        pending.thread_id,
        pending.approval_id,
        s.actor,
        ApprovalDecision(action="approve", expected_version=1, decision_key="approve-tamper"),
    )
    with s.store.factory.begin() as db:
        if corruption == "arguments":
            db.get(ApprovalRow, pending.approval_id).arguments = {
                **s.arguments,
                "customer_id": "C-OTHER",
            }
        else:
            row = db.get(SessionRow, pending.thread_id)
            row.data = {**row.data, "preflight": None}
    with runtime(s) as restarted:
        failed = restarted.resume(pending.thread_id)
    assert failed.status == "failed"
    assert failed.error == ErrorCode.CONFLICT.value
    with s.store.factory() as db:
        assert db.get(EffectRow, pending.approval_id) is None


def test_preflight_tool_and_policy_calls_have_correlated_payload_free_spans(workflow):
    telemetry = Telemetry()
    try:
        with telemetry.activate(request_id="preflight-trace"):
            pending = start(workflow)
        records = telemetry.local.snapshot()
        tool = next(item for item in records if item["name"] == "tool")
        retrieval = next(item for item in records if item["name"] == "retrieval")
        assert tool["attributes"]["tool_id"] == workflow.read.name
        assert tool["attributes"]["run_id"] == retrieval["attributes"]["run_id"] == pending.run_id
        assert "C-100" not in json.dumps(records)
        assert "Discount requests" not in json.dumps(records)
    finally:
        telemetry.shutdown()


def test_preflight_read_and_final_write_share_the_run_tool_budget(workflow):
    s = workflow
    profile = s.profile.model_copy(
        update={"budgets": s.profile.budgets.model_copy(update={"max_tool_calls": 1})}
    )
    with s.store.factory.begin() as db:
        SqlAlchemyAgentProfileRepository(db).save(profile)
    pending = start(s)
    assert pending.status == "awaiting_approval"
    with runtime(s) as restarted:
        failed = restarted.decide(
            pending.thread_id,
            pending.approval_id,
            ApprovalDecision(action="approve", expected_version=1, decision_key="approve-budget"),
        )
    assert failed.status == "failed"
    assert failed.error == ErrorCode.BUDGET.value
    assert failed.usage.tool_calls == 1
    with s.store.factory() as db:
        assert db.get(EffectRow, pending.approval_id) is None
