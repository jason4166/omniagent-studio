import json
import os
import threading
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient
from sqlalchemy import delete, func, select

from omniagent.approvals import ApprovalService
from omniagent.checkpoints import migrate_checkpoints, postgres_saver
from omniagent.database import build_engine
from omniagent.db_models import AgentProfileRow, PromptVersionRow, ToolDefinitionRow
from omniagent.durable_runtime import DurableRuntime
from omniagent.errors import ErrorCode, PlatformError
from omniagent.execution import IdempotentMockAdapter
from omniagent.identity import DevUserContext
from omniagent.llm import FakeLLM, LLMResponse
from omniagent.postgres_repositories import (
    SqlAlchemyAgentProfileRepository,
    SqlAlchemyPromptVersionRepository,
    SqlAlchemyToolDefinitionRepository,
)
from omniagent.profiles import AgentProfile
from omniagent.prompts import PromptVersionService
from omniagent.session_api import build_session_router, current_user
from omniagent.session_models import ApprovalDecision
from omniagent.session_rows import ApprovalRow, EffectRow, EventRow, SessionRow
from omniagent.session_store import SessionStore
from omniagent.tool_registry import ToolRegistry
from omniagent.tooling import ToolDefinition, ToolRisk

pytestmark = pytest.mark.integration


class EmptyRetriever:
    def retrieve_hits(self, knowledge_base_ids: list[str], query: str) -> list[object]:
        return []


@pytest.fixture
def scenario() -> Iterator[tuple[SessionStore, AgentProfile, DevUserContext, ToolRegistry, str]]:
    url = os.environ.get("OMNIAGENT_TEST_DATABASE_URL")
    if not url:
        pytest.skip("OMNIAGENT_TEST_DATABASE_URL required")
    engine = build_engine(url)
    store = SessionStore(engine)
    migrate_checkpoints(url)
    suffix = uuid4().hex
    actor = DevUserContext(user_id=f"test-{suffix}", role="admin")
    definition = ToolDefinition(
        name=f"write-{suffix}",
        risk=ToolRisk.MEDIUM,
        effect="write",
        allowed_roles=("admin",),
        parameters_schema={
            "type": "object",
            "properties": {"note": {"type": "string", "maxLength": 100}},
            "required": ["note"],
            "additionalProperties": False,
        },
    )
    registry = ToolRegistry()
    registry.register(definition, IdempotentMockAdapter(store, definition.name))
    profile = AgentProfile(
        profile_id=f"profile-{suffix}",
        prompt_version_id=f"prompt-{suffix}",
        tool_ids=[definition.name],
        budget_policy_id="standard",
        approval_policy_id="safe-default",
    )
    with store.factory.begin() as db:
        PromptVersionService(SqlAlchemyPromptVersionRepository(db)).create(
            prompt_version_id=profile.prompt_version_id,
            content="Propose a registered tool.",
            created_at=datetime.now(UTC),
        )
        SqlAlchemyToolDefinitionRepository(db).save(definition)
        SqlAlchemyAgentProfileRepository(db).save(profile)
    yield store, profile, actor, registry, url
    with store.factory.begin() as db:
        threads = list(
            db.scalars(select(SessionRow.thread_id).where(SessionRow.user_id == actor.user_id))
        )
        with postgres_saver(url) as saver:
            for thread_id in threads:
                saver.delete_thread(thread_id)
        db.execute(delete(SessionRow).where(SessionRow.user_id == actor.user_id))
        db.execute(delete(AgentProfileRow).where(AgentProfileRow.profile_id == profile.profile_id))
        db.execute(delete(ToolDefinitionRow).where(ToolDefinitionRow.tool_id == definition.name))
        db.execute(
            delete(PromptVersionRow).where(
                PromptVersionRow.prompt_version_id == profile.prompt_version_id
            )
        )
        db.execute(delete(EffectRow).where(EffectRow.tool_name == definition.name))
    engine.dispose()


@contextmanager
def runtime(scenario, *, fault=None):
    store, profile, actor, registry, url = scenario
    provider = FakeLLM(
        LLMResponse(
            model="fake-v1",
            content=(
                '{"route":"tool","reason":"Requested operation","confidence":1,'
                f'"tool_name":"{profile.tool_ids[0]}","args":{{"note":"original"}}}}'
            ),
        )
    )
    with postgres_saver(url) as saver:
        yield DurableRuntime(
            store, saver, actor, provider, registry, EmptyRetriever(), failure_hook=fault
        )


def propose(scenario):
    store, profile, actor, _, _ = scenario
    data = store.create(profile.profile_id, actor)
    with runtime(scenario) as service:
        data = service.send(data.thread_id, "create a followup", "message-1")
    assert data.status == "awaiting_approval", data
    return data


def test_running_cancel_is_durable_and_stops_next_boundary_without_sleep(scenario):
    store, profile, actor, _, _ = scenario
    entered, release = threading.Event(), threading.Event()
    data = store.create(profile.profile_id, actor)

    def block_response(boundary):
        if boundary == "before_respond":
            entered.set()
            assert release.wait(10), "test did not release the paused worker"

    pending = propose(scenario)
    with runtime(scenario, fault=block_response) as worker, runtime(scenario) as controller:
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(
                worker.decide,
                pending.thread_id,
                pending.approval_id,
                ApprovalDecision(
                    action="approve", expected_version=1, decision_key="cancel-flight"
                ),
            )
            try:
                assert entered.wait(10)
                assert controller.cancel(pending.thread_id).status == "cancelled"
                assert controller.cancel(pending.thread_id).status == "cancelled"
            finally:
                release.set()
            assert future.result(timeout=10).status == "cancelled"
        # The tool completed before cancellation; it remains recorded, never disguised as undone.
        with store.factory() as db:
            approval = db.get(ApprovalRow, pending.approval_id)
            assert approval.status == "executed"
            events = list(
                db.scalars(select(EventRow.kind).where(EventRow.thread_id == pending.thread_id))
            )
            assert events.count("run.cancelled") == 1
            assert "run.completed" not in events
        with pytest.raises(PlatformError):
            controller.resume(pending.thread_id)
        assert controller.cancel(data.thread_id).status == "cancelled"


def test_cancel_while_model_is_pending_never_creates_a_write_proposal(scenario):
    store, profile, actor, registry, url = scenario
    entered, release = threading.Event(), threading.Event()

    class PendingProvider:
        def generate(self, request):
            entered.set()
            assert release.wait(10)
            return LLMResponse(
                model="fake-v1",
                content=json.dumps(
                    {
                        "route": "tool",
                        "reason": "requested",
                        "confidence": 1,
                        "tool_name": profile.tool_ids[0],
                        "args": {"note": "must not execute"},
                    }
                ),
            )

    data = store.create(profile.profile_id, actor)
    with postgres_saver(url) as saver, runtime(scenario) as controller:
        worker = DurableRuntime(store, saver, actor, PendingProvider(), registry, EmptyRetriever())
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(worker.send, data.thread_id, "write", "cancel-model")
            try:
                assert entered.wait(10)
                assert controller.cancel(data.thread_id).status == "cancelled"
            finally:
                release.set()
            assert future.result(timeout=10).status == "cancelled"
        with store.factory() as db:
            assert (
                db.scalar(select(ApprovalRow).where(ApprovalRow.thread_id == data.thread_id))
                is None
            )


def test_restart_edit_approve_and_response_replay_produce_one_effect(scenario) -> None:
    data = propose(scenario)
    store, _, actor, registry, _ = scenario
    decision = ApprovalDecision(
        action="edit", expected_version=1, decision_key="decision-1", arguments={"note": "edited"}
    )
    with runtime(scenario) as service:
        result = service.decide(data.thread_id, data.approval_id, decision)
        replay = service.decide(data.thread_id, data.approval_id, decision)
        assert result.status == replay.status == "completed", result
        assert service.send(data.thread_id, "create a followup", "message-1").run_id == data.run_id
    approval = ApprovalService(store, registry).get(data.thread_id, data.approval_id, actor)
    assert approval["status"] == "executed"
    assert approval["arguments"] == {"note": "edited"}
    with store.factory() as db:
        assert (
            db.scalar(
                select(func.count())
                .select_from(EffectRow)
                .where(EffectRow.idempotency_key == data.approval_id)
            )
            == 1
        )


@pytest.mark.parametrize("boundary", ["before_tool", "after_tool", "before_respond"])
def test_failure_recovery_preserves_budget_and_idempotency(scenario, boundary) -> None:
    data = propose(scenario)
    fired = False

    def fault(point):
        nonlocal fired
        if point == boundary and not fired:
            fired = True
            raise ConnectionError("injected dependency failure")

    with runtime(scenario, fault=fault) as service:
        failed = service.decide(
            data.thread_id,
            data.approval_id,
            ApprovalDecision(action="approve", expected_version=1, decision_key="decision-1"),
        )
    assert failed.status == "failed"
    with runtime(scenario) as service:
        recovered = service.resume(data.thread_id)
    assert recovered.status == "completed", recovered
    assert recovered.usage.steps >= failed.usage.steps
    store = scenario[0]
    with store.factory() as db:
        assert (
            db.scalar(
                select(func.count())
                .select_from(EffectRow)
                .where(EffectRow.idempotency_key == data.approval_id)
            )
            == 1
        )


@pytest.mark.parametrize(
    "mutation", ["role", "profile_version", "tool_version", "schema", "replay"]
)
def test_edited_and_replayed_approvals_are_revalidated(scenario, mutation) -> None:
    data = propose(scenario)
    store, profile, actor, registry, _ = scenario
    args = {"note": "safe"}
    if mutation == "role":
        definition = registry.definition(profile.tool_ids[0])
        definition.allowed_roles = ("viewer",)
        registry.register(definition, IdempotentMockAdapter(store, definition.name))
    elif mutation == "tool_version":
        definition = registry.definition(profile.tool_ids[0])
        definition.version += 1
        registry.register(definition, IdempotentMockAdapter(store, definition.name))
    elif mutation == "profile_version":
        with store.factory.begin() as db:
            row = db.get(AgentProfileRow, profile.profile_id)
            row.version += 1
    elif mutation == "schema":
        args["unexpected"] = "injected"
    decision = ApprovalDecision(
        action="edit", expected_version=1, decision_key="decision-1", arguments=args
    )
    with runtime(scenario) as service:
        if mutation == "replay":
            service.decide(data.thread_id, data.approval_id, decision)
            decision.arguments = {"note": "different"}
        with pytest.raises(PlatformError):
            service.decide(data.thread_id, data.approval_id, decision)


def test_cancel_reject_and_expiry_cannot_execute(scenario) -> None:
    store, _, actor, registry, _ = scenario
    for action in ("cancel", "reject", "expire"):
        data = propose(scenario)
        with runtime(scenario) as service:
            if action == "cancel":
                service.cancel(data.thread_id)
                with pytest.raises(PlatformError):
                    service.resume(data.thread_id)
            elif action == "reject":
                result = service.decide(
                    data.thread_id,
                    data.approval_id,
                    ApprovalDecision(
                        action="reject", expected_version=1, decision_key="decision-1"
                    ),
                )
                assert result.result["status"] == "rejected"
            else:
                with store.factory.begin() as db:
                    row = db.get(ApprovalRow, data.approval_id)
                    row.expires_at = datetime(2000, 1, 1, tzinfo=UTC)
                assert (
                    ApprovalService(store, registry).get(data.thread_id, data.approval_id, actor)[
                        "status"
                    ]
                    == "expired"
                )
                with pytest.raises(PlatformError):
                    service.decide(
                        data.thread_id,
                        data.approval_id,
                        ApprovalDecision(
                            action="approve", expected_version=1, decision_key="decision-1"
                        ),
                    )
        with store.factory() as db:
            assert db.get(EffectRow, data.approval_id) is None


def test_concurrent_approval_has_one_winner_or_identical_replay(scenario) -> None:
    data = propose(scenario)
    decision = ApprovalDecision(action="approve", expected_version=1, decision_key="decision-1")

    def approve():
        try:
            with runtime(scenario) as service:
                return service.decide(data.thread_id, data.approval_id, decision).status
        except PlatformError as exc:
            return exc.code

    with ThreadPoolExecutor(max_workers=2) as pool:
        statuses = list(pool.map(lambda _: approve(), range(2)))
    assert "completed" in statuses
    assert set(statuses) <= {"completed", ErrorCode.CONFLICT}
    with scenario[0].factory() as db:
        assert (
            db.scalar(
                select(func.count())
                .select_from(EffectRow)
                .where(EffectRow.idempotency_key == data.approval_id)
            )
            == 1
        )


@pytest.mark.parametrize("mutation", ["user", "profile", "ttl", "schema", "delete", "budget"])
def test_checkpoint_isolation_and_terminal_guards(scenario, mutation) -> None:
    data = propose(scenario)
    store, profile, actor, _, _ = scenario
    with runtime(scenario) as service:
        if mutation == "user":
            service.actor = DevUserContext(user_id="other", role="admin")
        elif mutation == "profile":
            with store.factory.begin() as db:
                db.get(AgentProfileRow, profile.profile_id).enabled = False
        elif mutation == "delete":
            service.delete(data.thread_id)
        else:
            with store.factory.begin() as db:
                row = db.get(SessionRow, data.thread_id)
                if mutation == "ttl":
                    row.expires_at = datetime(2000, 1, 1, tzinfo=UTC)
                elif mutation == "schema":
                    row.data = {**row.data, "schema_version": 999}
                else:
                    row.data = {**row.data, "deadline_at": 1}
        with pytest.raises(PlatformError):
            service.resume(data.thread_id)


def test_http_session_approval_and_owner_boundary(scenario) -> None:
    store, profile, actor, _, _ = scenario
    app = FastAPI()

    @app.exception_handler(PlatformError)
    def error(_request: Request, exc: PlatformError) -> JSONResponse:
        return JSONResponse({"error": {"code": exc.code}}, status_code=exc.status_code)

    app.include_router(build_session_router(store, lambda _actor, _profile: runtime(scenario)))
    with TestClient(app) as client:
        assert client.get("/api/sessions").status_code == 401
        app.dependency_overrides[current_user] = lambda: actor
        created = client.post("/api/sessions", json={"profile_id": profile.profile_id})
        assert created.status_code == 201
        thread_id = created.json()["thread_id"]
        path = f"/api/sessions/{thread_id}"
        proposed = client.post(
            path + "/messages",
            json={
                "message": "create followup",
                "request_key": "request-1",
            },
        ).json()
        assert proposed["status"] == "awaiting_approval"
        assert client.post(path + "/resume").json()["status"] == "awaiting_approval"
        approved = client.post(
            path + "/approvals/" + proposed["approval_id"],
            json={
                "action": "approve",
                "expected_version": 1,
                "decision_key": "decision-1",
            },
        )
        assert approved.status_code == 200
        assert approved.json()["status"] == "completed"
        app.dependency_overrides[current_user] = lambda: DevUserContext(
            user_id="other", role="admin"
        )
        assert client.get(path).status_code == 404
        assert client.post(path + "/resume").status_code == 404


def test_unknown_checkpoint_schema_and_missing_budget_fail_closed(scenario) -> None:
    data = propose(scenario)
    store, _, actor, _, _ = scenario
    with store.factory.begin() as db:
        row = db.get(SessionRow, data.thread_id)
        row.data = {key: value for key, value in row.data.items() if key != "usage"}
    with pytest.raises(PlatformError, match="schema"):
        store.load(data.thread_id, actor)


def test_checkpoint_contains_data_only_and_ttl_purge_erases_it(scenario) -> None:
    data = propose(scenario)
    with runtime(scenario) as service:
        saved = service.graph.get_state(service.config(data.thread_id))
        encoded = json.dumps(saved.values)
        assert "Propose a registered tool." not in encoded
        assert "postgresql" not in encoded
        assert "local-demo-admin" not in encoded
        with scenario[0].factory.begin() as db:
            db.get(SessionRow, data.thread_id).expires_at = datetime(2000, 1, 1, tzinfo=UTC)
        assert service.purge_expired() == 1
        assert not service.graph.get_state(service.config(data.thread_id)).values


def test_privileged_retention_erases_expired_corrupt_sessions_without_loading_them(scenario):
    from omniagent.maintenance import purge

    expired = propose(scenario)
    active = propose(scenario)
    store, _, actor, _, url = scenario
    with store.factory.begin() as db:
        row = db.get(SessionRow, expired.thread_id)
        row.expires_at = datetime(2000, 1, 1, tzinfo=UTC)
        row.data = {"schema_version": 999}
    assert purge(url)["expired_sessions_deleted"] >= 1
    assert store.load(active.thread_id, actor).status == "awaiting_approval"
    with store.factory() as db:
        assert db.get(SessionRow, expired.thread_id) is None
        assert db.get(ApprovalRow, expired.approval_id) is None
    with runtime(scenario) as service:
        assert not service.graph.get_state(service.config(expired.thread_id)).values
