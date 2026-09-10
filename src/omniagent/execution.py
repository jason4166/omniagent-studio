"""Internal execution identity and transactional local business idempotency."""

from contextvars import ContextVar
from datetime import UTC, datetime

from sqlalchemy import select, text

from omniagent.errors import ErrorCode, PlatformError
from omniagent.session_rows import EffectRow
from omniagent.session_store import SessionStore, digest

execution_key: ContextVar[str | None] = ContextVar("execution_key", default=None)


class IdempotentMockAdapter:
    def __init__(self, store: SessionStore, tool_name: str) -> None:
        self.store = store
        self.tool_name = tool_name

    def execute(self, arguments: dict[str, object]) -> object:
        key = execution_key.get()
        if key is None:
            raise PlatformError(ErrorCode.PERMISSION)
        fingerprint = digest({"tool": self.tool_name, "arguments": arguments})
        with self.store.factory.begin() as db:
            # Transaction-scoped serialization also covers two distinct runtime processes.
            db.execute(
                text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"), {"key": key}
            )
            existing = db.scalar(select(EffectRow).where(EffectRow.idempotency_key == key))
            if existing:
                if existing.payload_hash != fingerprint:
                    raise PlatformError(ErrorCode.CONFLICT)
                return existing.result
            result: dict[str, object] = {
                "operation_id": key,
                "tool": self.tool_name,
                "status": "created",
            }
            db.add(
                EffectRow(
                    idempotency_key=key,
                    payload_hash=fingerprint,
                    tool_name=self.tool_name,
                    result=result,
                    created_at=datetime.now(UTC),
                )
            )
            return result
