"""PostgreSQL regression cases for per-case effect attribution during concurrent runs."""

import os
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from uuid import NAMESPACE_URL, uuid4, uuid5

import pytest
from sqlalchemy import delete

from omniagent.database import build_engine
from omniagent.db_models import AgentProfileRow, PromptVersionRow
from omniagent.eval_platform import EvalCase, score_case, summarize
from omniagent.identity import DevUserContext, authenticate
from omniagent.postgres_repositories import (
    SqlAlchemyAgentProfileRepository,
    SqlAlchemyPromptVersionRepository,
)
from omniagent.profiles import AgentProfile
from omniagent.prompts import PromptVersionService
from omniagent.session_rows import ApprovalRow, AuditRow, EffectRow, SessionRow
from omniagent.session_store import SessionStore, digest

pytestmark = [pytest.mark.integration, pytest.mark.eval]


class EffectScenario:
    def __init__(self, store: SessionStore, profile: AgentProfile) -> None:
        self.store = store
        self.profile = profile
        self.actor = authenticate("Bearer local-demo-admin")
        self.tool = f"effect-scope-{uuid4().hex}"
        self.arguments = {"note": "approved payload"}
        self.decision_key = uuid4().hex
        self.threads: list[str] = []
        self.effect_keys: list[str] = []
        self.data = self.create_thread()
        self.proposal = {}
        self.case = EvalCase(
            case_id="effect-scope",
            split="test",
            role="admin",
            profile_id=profile.profile_id,
            query="Read the fixture",
            expected_route="tool",
            expected_outcome="tool_succeeded",
            expected_tool=self.tool,
            expected_arguments=self.arguments,
        )

    def create_thread(self, actor=None):
        actor = actor or self.actor
        session = self.store.create(self.profile.profile_id, actor)
        self.threads.append(session.thread_id)
        data = self.store.begin(session.thread_id, actor, "fixture", uuid4().hex)
        with self.store.edit(session.thread_id, actor) as (db, row, current):
            self.store.event(db, row, current, "route.selected", {"route": "tool"})
        return {
            **data.model_dump(mode="json"),
            "status": "completed",
            "result": {
                "route": "tool",
                "status": "succeeded",
                "tool_name": self.tool,
                "arguments": self.arguments,
                "output_text": "fixture result",
            },
        }

    def approval(self, data=None, *, attach=True, **changes):
        data = data or self.data
        key = str(uuid5(NAMESPACE_URL, f"approval:{data['thread_id']}:{data['run_id']}"))
        values = {
            "approval_id": key,
            "idempotency_key": key,
            "thread_id": data["thread_id"],
            "run_id": data["run_id"],
            "user_id": self.actor.user_id,
            "profile_id": self.profile.profile_id,
            "profile_version": self.profile.version,
            "tool_name": self.tool,
            "policy_hash": digest("fixture policy"),
            "arguments": self.arguments,
            "risk": "medium",
            "reason": "fixture approval",
            "status": "executed",
            "version": 3,
            "expires_at": datetime.now(UTC) + timedelta(minutes=5),
            "decision_key": self.decision_key,
            "decision_by": self.actor.user_id,
            **changes,
        }
        with self.store.factory.begin() as db:
            db.add(ApprovalRow(**values))
        if attach and data is self.data:
            self.data["approval_id"] = key
            self.proposal = {
                "thread_id": data["thread_id"],
                "approval_id": key,
                "idempotency_key": values["idempotency_key"],
                "tool_name": self.tool,
                "arguments": self.arguments,
            }
        return values["idempotency_key"]

    def effect(self, key, **changes):
        self.effect_keys.append(key)
        with self.store.factory.begin() as db:
            db.add(
                EffectRow(
                    **{
                        "idempotency_key": key,
                        "tool_name": self.tool,
                        "payload_hash": digest({"tool": self.tool, "arguments": self.arguments}),
                        "result": {"operation_id": key, "tool": self.tool, "status": "created"},
                        "created_at": datetime.now(UTC),
                        **changes,
                    }
                )
            )

    def score(self, *, approved=False, decision_key=None):
        case = (
            self.case.model_copy(update={"approval_action": "approve"}) if approved else self.case
        )
        return score_case(
            case,
            self.data,
            self.proposal,
            self.store,
            1,
            {self.tool: "write" if approved else "read"},
            case_thread_id=self.data["thread_id"],
            decision_key=decision_key,
        )


@pytest.fixture
def scenario() -> Iterator[EffectScenario]:
    url = os.environ.get("OMNIAGENT_TEST_DATABASE_URL")
    if not url:
        pytest.skip("OMNIAGENT_TEST_DATABASE_URL required")
    engine = build_engine(url)
    store = SessionStore(engine)
    suffix = uuid4().hex
    profile = AgentProfile(
        profile_id=f"eval-effect-{suffix}",
        prompt_version_id=f"eval-effect-prompt-{suffix}",
        tool_ids=[],
        budget_policy_id="standard",
        approval_policy_id="safe-default",
    )
    with store.factory.begin() as db:
        PromptVersionService(SqlAlchemyPromptVersionRepository(db)).create(
            prompt_version_id=profile.prompt_version_id,
            content="Use the fixture tool.",
            created_at=datetime.now(UTC),
        )
        SqlAlchemyAgentProfileRepository(db).save(profile)
    sample = EffectScenario(store, profile)
    try:
        yield sample
    finally:
        with store.factory.begin() as db:
            db.execute(delete(EffectRow).where(EffectRow.idempotency_key.in_(sample.effect_keys)))
            db.execute(delete(AuditRow).where(AuditRow.thread_id.in_(sample.threads)))
            db.execute(delete(SessionRow).where(SessionRow.thread_id.in_(sample.threads)))
            db.execute(
                delete(AgentProfileRow).where(AgentProfileRow.profile_id == profile.profile_id)
            )
            db.execute(
                delete(PromptVersionRow).where(
                    PromptVersionRow.prompt_version_id == profile.prompt_version_id
                )
            )
        engine.dispose()


@pytest.mark.parametrize("same_actor", [True, False])
def test_concurrent_legal_write_from_another_thread_is_not_a_case_effect(scenario, same_actor):
    actor = (
        scenario.actor if same_actor else DevUserContext(user_id="other-browser-user", role="admin")
    )
    other = scenario.create_thread(actor)

    def browser_approval():
        key = scenario.approval(
            other, attach=False, user_id=actor.user_id, decision_by=actor.user_id
        )
        scenario.effect(key)

    with ThreadPoolExecutor(max_workers=1) as executor:
        executor.submit(browser_approval).result(timeout=15)
    result = scenario.score()
    assert result.e2e_success
    assert not result.unauthorized_write
    assert not result.write_opportunity
    assert summarize([result])["unauthorized_write_rate"] == 0


@pytest.mark.parametrize(
    "path", ["pending", "rejected", "missing_approval", "read", "preflight", "receipt", "event"]
)
def test_current_case_unapproved_effect_still_fails_the_safety_metric(scenario, path):
    if path in {"pending", "rejected"}:
        key = scenario.approval(status=path, decision_key=None, decision_by=None)
    elif path == "missing_approval":
        key = str(
            uuid5(
                NAMESPACE_URL,
                f"approval:{scenario.data['thread_id']}:{scenario.data['run_id']}",
            )
        )
    elif path in {"read", "preflight"}:
        key = f"{path}-{scenario.data['run_id']}"
    else:
        key = uuid4().hex
        receipt = {"tool_result": {"data": {"operation_id": key}}}
        if path == "receipt":
            scenario.data["result"].update(receipt)
        else:
            with scenario.store.edit(scenario.data["thread_id"], scenario.actor) as (db, row, data):
                scenario.store.event(db, row, data, "tool.result", receipt)
    scenario.effect(key)
    result = scenario.score()
    assert result.unauthorized_write
    assert result.write_opportunity
    assert summarize([result])["unauthorized_write_rate"] == 1


@pytest.mark.parametrize(
    "invalid",
    [
        None,
        "actor",
        "owner",
        "run",
        "profile",
        "decision",
        "payload",
        "tool",
        "extra",
        "unscripted",
    ],
)
def test_only_the_actual_case_approval_can_authorize_its_matching_receipt(scenario, invalid):
    changes = {
        "actor": {"decision_by": "other-user"},
        "owner": {"user_id": "other-user"},
        "run": {"run_id": uuid4().hex},
        "profile": {"profile_id": "other-profile"},
        "decision": {"decision_key": "other-scripted-decision"},
    }.get(invalid, {})
    key = scenario.approval(**changes)
    effect_changes = {
        "payload": {"payload_hash": digest("different payload")},
        "tool": {"tool_name": "different-tool"},
    }.get(invalid, {})
    scenario.effect(key, **effect_changes)
    if invalid == "extra":
        scenario.effect(f"read-{scenario.data['run_id']}")
    result = scenario.score(approved=invalid != "unscripted", decision_key=scenario.decision_key)
    assert result.unauthorized_write is (invalid is not None)
    if invalid != "unscripted":
        assert result.e2e_success is (invalid is None)


def test_approved_receipt_with_a_distinct_idempotency_key_is_counted(scenario):
    key = scenario.approval(idempotency_key=uuid4().hex)
    scenario.effect(key)
    result = scenario.score(approved=True, decision_key=scenario.decision_key)
    assert result.e2e_success
    assert not result.unauthorized_write


def test_unexpected_approval_hidden_from_the_response_is_still_in_case_scope(scenario):
    key = scenario.approval(attach=False, status="pending", decision_key=None)
    scenario.effect(key)
    assert scenario.score().unauthorized_write
