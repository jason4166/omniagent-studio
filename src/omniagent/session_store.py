"""PostgreSQL transactions are the authority for ownership, budgets and replay."""

import hashlib
import json
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from time import time
from uuid import uuid4

from pydantic import ValidationError
from sqlalchemy import Engine, select, text
from sqlalchemy.orm import Session, sessionmaker

from omniagent.context import HistoryMessage
from omniagent.errors import ErrorCode, PlatformError
from omniagent.identity import DevUserContext
from omniagent.llm import LLMUsage
from omniagent.postgres_repositories import SqlAlchemyAgentProfileRepository
from omniagent.profiles import AgentProfile
from omniagent.redaction import redact_text
from omniagent.session_models import SessionData, Usage
from omniagent.session_rows import AuditRow, EventRow, RequestRow, SessionRow
from omniagent.telemetry import trace_metadata


def digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False).encode()
    ).hexdigest()


class SessionStore:
    def __init__(self, engine: Engine, clock: Callable[[], float] = time) -> None:
        self.engine = engine
        self.factory = sessionmaker(engine, expire_on_commit=False)
        self.clock = clock

    @contextmanager
    def lock(self, thread_id: str) -> Iterator[None]:
        key = int.from_bytes(hashlib.sha256(thread_id.encode()).digest()[:8], signed=True)
        with self.engine.connect() as connection:
            locked = connection.scalar(text("SELECT pg_try_advisory_lock(:key)"), {"key": key})
            connection.commit()
            if not locked:
                raise PlatformError(ErrorCode.CONFLICT, "Session is busy; retry with the same key")
            try:
                yield
            finally:
                connection.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": key})
                connection.commit()

    def profile(self, profile_id: str, actor: DevUserContext) -> AgentProfile:
        with self.factory() as db:
            profile = SqlAlchemyAgentProfileRepository(db).get(profile_id)
        if profile is None:
            raise PlatformError(ErrorCode.NOT_FOUND)
        actor.authorize_profile(profile)
        return profile

    def decode(self, row: SessionRow, actor: DevUserContext) -> SessionData:
        if row.user_id != actor.user_id:
            raise PlatformError(ErrorCode.NOT_FOUND)
        if row.expires_at.timestamp() <= self.clock():
            raise PlatformError(ErrorCode.EXPIRED)
        usage = row.data.get("usage")
        if (
            set(row.data) != set(SessionData.model_fields)
            or not isinstance(usage, dict)
            or set(usage) != set(Usage.model_fields)
        ):
            raise PlatformError(ErrorCode.SCHEMA)
        try:
            data = SessionData.model_validate(row.data)
        except ValidationError as exc:
            raise PlatformError(ErrorCode.SCHEMA) from exc
        if (
            data.thread_id != row.thread_id
            or data.profile_id != row.profile_id
            or data.user_id != row.user_id
        ):
            raise PlatformError(ErrorCode.SCHEMA)
        return data

    def load(self, thread_id: str, actor: DevUserContext) -> SessionData:
        with self.factory() as db:
            row = db.get(SessionRow, thread_id)
            if row is None:
                raise PlatformError(ErrorCode.NOT_FOUND)
            data = self.decode(row, actor)
        self.profile(data.profile_id, actor)
        return data

    @contextmanager
    def edit(
        self, thread_id: str, actor: DevUserContext
    ) -> Iterator[tuple[Session, SessionRow, SessionData]]:
        with self.factory.begin() as db:
            row = db.scalar(
                select(SessionRow).where(SessionRow.thread_id == thread_id).with_for_update()
            )
            if row is None:
                raise PlatformError(ErrorCode.NOT_FOUND)
            data = self.decode(row, actor)
            yield db, row, data
            row.data = data.model_dump(mode="json")

    def audit(self, db: Session, data: SessionData, action: str, **details: object) -> None:
        # Only stable identifiers, codes, counts and hashes are accepted by callers.
        db.add(
            AuditRow(
                audit_id=str(uuid4()),
                actor_hash=digest(data.user_id),
                thread_id=data.thread_id,
                run_id=data.run_id,
                action=action,
                details={**details, **trace_metadata()},
                created_at=datetime.fromtimestamp(self.clock(), UTC),
            )
        )

    def event(
        self, db: Session, row: SessionRow, data: SessionData, kind: str, payload: dict[str, object]
    ) -> None:
        row.sequence += 1
        db.add(
            EventRow(
                event_id=f"{row.thread_id}:{row.sequence}",
                thread_id=row.thread_id,
                run_id=data.run_id,
                sequence=row.sequence,
                kind=kind,
                data={**payload, "trace": trace_metadata()},
                created_at=datetime.fromtimestamp(self.clock(), UTC),
            )
        )

    def create(self, profile_id: str, actor: DevUserContext) -> SessionData:
        profile = self.profile(profile_id, actor)
        data = SessionData(
            thread_id=str(uuid4()),
            user_id=actor.user_id,
            profile_id=profile_id,
            profile_version=profile.version,
            status="ready",
        )
        with self.factory.begin() as db:
            row = SessionRow(
                thread_id=data.thread_id,
                user_id=actor.user_id,
                profile_id=profile_id,
                data=data.model_dump(mode="json"),
                sequence=0,
                expires_at=datetime.fromtimestamp(self.clock(), UTC)
                + timedelta(seconds=profile.context_policy.ttl_seconds),
            )
            db.add(row)
            self.audit(db, data, "session.created")
        return data

    def begin(
        self, thread_id: str, actor: DevUserContext, message: str, request_key: str
    ) -> SessionData:
        current = self.load(thread_id, actor)
        profile = self.profile(current.profile_id, actor)
        if not message.strip() or len(message) > 8000 or not 8 <= len(request_key) <= 128:
            raise PlatformError(ErrorCode.VALIDATION)
        payload_hash = digest(message)
        with self.edit(thread_id, actor) as (db, row, data):
            existing = db.get(RequestRow, (thread_id, request_key))
            if existing:
                if existing.payload_hash != payload_hash:
                    raise PlatformError(ErrorCode.CONFLICT, "Idempotency key payload mismatch")
                if existing.response is not None:
                    return SessionData.model_validate(existing.response)
                return data
            if data.status in ("running", "awaiting_approval", "cancelled", "failed"):
                raise PlatformError(ErrorCode.CONFLICT, "Resume or cancel the current run first")
            data.run_id = str(uuid4())
            data.request_key = request_key
            data.request_hash = payload_hash
            data.message = redact_text(message)
            data.profile_version = profile.version
            data.status = "running"
            data.result = None
            data.error = None
            data.approval_id = None
            data.usage = Usage()
            data.deadline_at = self.clock() + profile.budgets.deadline_seconds
            db.add(
                RequestRow(
                    thread_id=thread_id,
                    request_key=request_key,
                    payload_hash=payload_hash,
                    run_id=data.run_id,
                )
            )
            self.event(db, row, data, "run.started", {})
            self.audit(db, data, "run.started", input_hash=payload_hash)
        return data

    def guard(
        self, thread_id: str, run_id: str, actor: DevUserContext
    ) -> tuple[SessionData, AgentProfile]:
        data = self.load(thread_id, actor)
        profile = self.profile(data.profile_id, actor)
        if data.run_id != run_id or data.profile_version != profile.version:
            raise PlatformError(ErrorCode.CONFLICT, "Run or profile version changed")
        if data.status == "cancelled":
            raise PlatformError(ErrorCode.CANCELLED)
        if data.deadline_at and self.clock() >= data.deadline_at:
            raise PlatformError(ErrorCode.BUDGET, "Run deadline exhausted")
        return data, profile

    def reserve(
        self,
        thread_id: str,
        run_id: str,
        actor: DevUserContext,
        node: str,
        *,
        tokens: int = 0,
        model: bool = False,
        tool: bool = False,
        retrieval: bool = False,
    ) -> None:
        _, profile = self.guard(thread_id, run_id, actor)
        budget = profile.budgets
        with self.edit(thread_id, actor) as (db, row, data):
            usage = data.usage
            if (
                usage.steps + 1 > budget.max_steps
                or usage.model_calls + int(model) > budget.max_model_calls
                or usage.tool_calls + int(tool) > budget.max_tool_calls
                or usage.reserved_tokens + tokens > budget.max_tokens
            ):
                raise PlatformError(ErrorCode.BUDGET)
            if model and budget.max_cost_microusd is not None and profile.provider_id != "fake":
                raise PlatformError(
                    ErrorCode.BUDGET, "No trusted price available for cost enforcement"
                )
            usage.steps += 1
            usage.model_calls += int(model)
            usage.tool_calls += int(tool)
            usage.retrieval_calls += int(retrieval)
            usage.reserved_tokens += tokens
            self.event(db, row, data, "node.status", {"node": node, "status": "running"})
            self.audit(db, data, "budget.reserved", node=node, tokens=tokens)

    def record_usage(
        self, thread_id: str, actor: DevUserContext, usage: LLMUsage | None, *, fake: bool
    ) -> None:
        current = self.load(thread_id, actor)
        budget = self.profile(current.profile_id, actor).budgets
        exceeded = False
        with self.edit(thread_id, actor) as (_, _, data):
            if usage is not None:
                if usage.total_tokens != usage.input_tokens + usage.output_tokens:
                    raise PlatformError(ErrorCode.BAD_RESPONSE)
                data.usage.input_tokens += usage.input_tokens
                data.usage.output_tokens += usage.output_tokens
                data.usage.total_tokens += usage.total_tokens
                data.usage.reserved_tokens = max(
                    data.usage.reserved_tokens, data.usage.total_tokens
                )
                exceeded = data.usage.total_tokens > budget.max_tokens
            data.usage.cost_microusd = 0 if fake else None
        if exceeded:
            raise PlatformError(ErrorCode.BUDGET, "Actual usage exceeded the reserved budget")

    def finish(
        self, thread_id: str, actor: DevUserContext, result: dict[str, object]
    ) -> SessionData:
        with self.edit(thread_id, actor) as (db, row, data):
            if data.status == "completed":
                return data
            data.status = "completed"
            output = str(result.get("output_text") or "")
            failure = result.get("error")
            if not output and isinstance(failure, dict):
                output = (
                    "当前知识库没有足够依据，无法回答这个问题。"
                    if failure.get("code") == "no_evidence"
                    else str(failure.get("message") or "Request could not be completed.")
                )
            result = {**result, "output_text": output}
            data.result = result
            data.history += [
                HistoryMessage(role="user", content=data.message),
                HistoryMessage(role="assistant", content=output[:8000]),
            ]
            data.history = data.history[-50:]
            # Validate the complete answer before releasing any of its chunks.
            for offset in range(0, len(output), 64):
                self.event(db, row, data, "message.delta", {"text": output[offset : offset + 64]})
            citations = result.get("citations", [])
            for citation in citations if isinstance(citations, list) else []:
                self.event(db, row, data, "citation.added", {"citation": citation})
            self.event(db, row, data, "run.completed", {"result": result})
            request = db.get(RequestRow, (thread_id, data.request_key))
            if request is not None:
                request.response = data.model_dump(mode="json")
            self.audit(db, data, "run.completed", output_hash=digest(result))
        return data

    def fail(self, thread_id: str, actor: DevUserContext, code: str) -> SessionData:
        with self.edit(thread_id, actor) as (db, row, data):
            data.status = "failed"
            data.error = code
            self.event(db, row, data, "run.failed", {"code": code})
            self.audit(db, data, "run.failed", code=code)
        return data
