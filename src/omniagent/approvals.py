"""Server-owned approval decisions with version and replay protection."""

from datetime import UTC, datetime, timedelta
from uuid import NAMESPACE_URL, uuid5

from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError
from sqlalchemy import select

from omniagent.errors import ErrorCode, PlatformError
from omniagent.identity import DevUserContext
from omniagent.profiles import AgentProfile
from omniagent.session_models import ApprovalDecision, SessionData
from omniagent.session_rows import ApprovalRow
from omniagent.session_store import SessionStore, digest
from omniagent.tool_registry import ToolRegistry
from omniagent.tooling import ToolDefinition, ToolRisk


def authorize_tool(
    registry: ToolRegistry,
    profile: AgentProfile,
    actor: DevUserContext,
    name: str,
    arguments: dict[str, object],
) -> ToolDefinition:
    actor.authorize_profile(profile)
    definition = registry.definition(name)
    if (
        definition is None
        or not definition.enabled
        or name not in profile.tool_ids
        or actor.role not in definition.allowed_roles
    ):
        raise PlatformError(ErrorCode.PERMISSION)
    try:
        Draft202012Validator(definition.parameters_schema).validate(arguments)
    except ValidationError as exc:
        raise PlatformError(
            ErrorCode.VALIDATION, "Tool arguments failed schema validation"
        ) from exc
    return definition


def needs_approval(definition: ToolDefinition, profile: AgentProfile) -> bool:
    return (
        definition.effect == "write"
        or definition.risk is not ToolRisk.LOW
        or definition.requires_approval
        or not profile.auto_approve_read
    )


def policy_hash(definition: ToolDefinition) -> str:
    return digest(definition.model_dump(mode="json"))


def approval_view(row: ApprovalRow) -> dict[str, object]:
    return {
        "approval_id": row.approval_id,
        "thread_id": row.thread_id,
        "run_id": row.run_id,
        "tool_name": row.tool_name,
        "arguments": row.arguments,
        "risk": row.risk,
        "reason": row.reason,
        "status": row.status,
        "version": row.version,
        "expires_at": row.expires_at.isoformat(),
        "decision_by": row.decision_by,
        "idempotency_key": row.idempotency_key,
        "result": row.result,
    }


class ApprovalService:
    def __init__(self, store: SessionStore, registry: ToolRegistry) -> None:
        self.store = store
        self.registry = registry

    def propose(
        self,
        data: SessionData,
        actor: DevUserContext,
        name: str,
        arguments: dict[str, object],
    ) -> str:
        profile = self.store.profile(data.profile_id, actor)
        definition = authorize_tool(self.registry, profile, actor, name, arguments)
        approval_id = str(uuid5(NAMESPACE_URL, f"approval:{data.thread_id}:{data.run_id}"))
        with self.store.edit(data.thread_id, actor) as (db, row, current):
            existing = db.get(ApprovalRow, approval_id)
            if existing:
                if existing.policy_hash != policy_hash(definition):
                    raise PlatformError(ErrorCode.CONFLICT)
                return approval_id
            approval = ApprovalRow(
                approval_id=approval_id,
                thread_id=data.thread_id,
                run_id=data.run_id,
                user_id=actor.user_id,
                profile_id=data.profile_id,
                profile_version=profile.version,
                tool_name=name,
                policy_hash=policy_hash(definition),
                arguments=arguments,
                risk=definition.risk.value,
                reason="This tool requires human authorization.",
                status="pending",
                version=1,
                expires_at=min(
                    row.expires_at,
                    datetime.fromtimestamp(self.store.clock(), UTC) + timedelta(minutes=30),
                ),
                idempotency_key=approval_id,
            )
            db.add(approval)
            current.approval_id = approval_id
            current.status = "awaiting_approval"
            current.remaining_seconds = max(0, current.deadline_at - self.store.clock())
            current.deadline_at = 0
            self.store.event(
                db,
                row,
                current,
                "tool.proposed",
                {
                    "tool_name": name,
                    "arguments": arguments,
                },
            )
            self.store.event(db, row, current, "approval.required", approval_view(approval))
            self.store.audit(
                db,
                current,
                "approval.created",
                approval_id=approval_id,
                arguments_hash=digest(arguments),
            )
        return approval_id

    def get(
        self,
        thread_id: str,
        approval_id: str,
        actor: DevUserContext,
    ) -> dict[str, object]:
        self.store.load(thread_id, actor)
        with self.store.factory.begin() as db:
            row = db.scalar(
                select(ApprovalRow)
                .where(
                    ApprovalRow.approval_id == approval_id,
                    ApprovalRow.thread_id == thread_id,
                )
                .with_for_update()
            )
            if row is None:
                raise PlatformError(ErrorCode.NOT_FOUND)
            if row.status == "pending" and row.expires_at.timestamp() <= self.store.clock():
                row.status = "expired"
                row.version += 1
            return approval_view(row)

    def decide(
        self,
        thread_id: str,
        approval_id: str,
        actor: DevUserContext,
        decision: ApprovalDecision,
    ) -> dict[str, object]:
        current = self.store.load(thread_id, actor)
        profile = self.store.profile(current.profile_id, actor)
        if current.status == "cancelled" or actor.role == "viewer":
            raise PlatformError(ErrorCode.PERMISSION)
        if self.get(thread_id, approval_id, actor)["status"] == "expired":
            raise PlatformError(ErrorCode.EXPIRED)
        with self.store.edit(thread_id, actor) as (db, session_row, data):
            row = db.scalar(
                select(ApprovalRow)
                .where(
                    ApprovalRow.approval_id == approval_id,
                    ApprovalRow.thread_id == thread_id,
                )
                .with_for_update()
            )
            if row is None or row.user_id != actor.user_id:
                raise PlatformError(ErrorCode.NOT_FOUND)
            fingerprint = digest(decision.model_dump(mode="json"))
            if row.decision_key == decision.decision_key:
                if row.decision_hash != fingerprint:
                    raise PlatformError(ErrorCode.CONFLICT, "Decision key payload mismatch")
                return approval_view(row)
            if row.status != "pending" or row.version != decision.expected_version:
                raise PlatformError(ErrorCode.CONFLICT)
            if row.profile_version != profile.version or row.run_id != data.run_id:
                raise PlatformError(ErrorCode.CONFLICT, "Profile or run changed")
            arguments = row.arguments
            if decision.action == "edit":
                if decision.arguments is None:
                    raise PlatformError(ErrorCode.VALIDATION)
                arguments = decision.arguments
            elif decision.arguments is not None:
                raise PlatformError(ErrorCode.VALIDATION)
            definition = authorize_tool(self.registry, profile, actor, row.tool_name, arguments)
            if row.policy_hash != policy_hash(definition):
                raise PlatformError(ErrorCode.CONFLICT, "Tool definition changed")
            row.arguments = arguments
            row.status = "rejected" if decision.action == "reject" else "approved"
            row.version += 1
            row.decision_by = actor.user_id
            row.decision_at = datetime.fromtimestamp(self.store.clock(), UTC)
            row.decision_key = decision.decision_key
            row.decision_hash = fingerprint
            data.status = "running"
            data.deadline_at = self.store.clock() + data.remaining_seconds
            self.store.event(db, session_row, data, "approval.decided", approval_view(row))
            self.store.audit(
                db,
                data,
                "approval.decided",
                action_kind=decision.action,
                approval_id=approval_id,
                arguments_hash=digest(arguments),
            )
            return approval_view(row)
