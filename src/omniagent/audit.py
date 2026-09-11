"""Configuration change evidence written in the caller's mutation transaction."""

import hashlib
import json
from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy.orm import Session

from omniagent.session_rows import AuditRow
from omniagent.telemetry import trace_metadata


def hashed(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()


def audit_change(
    db: Session,
    actor_id: str,
    action: str,
    object_id: str,
    *,
    before: dict[str, object] | None = None,
    after: dict[str, object] | None = None,
) -> None:
    """Store identifiers, versions and hashes; never copy configuration or account secrets."""
    previous, current = before or {}, after or {}
    db.add(
        AuditRow(
            audit_id=str(uuid4()),
            actor_hash=hashed(actor_id),
            thread_id="",
            run_id=None,
            action=action,
            details={
                "object_hash": hashed(object_id),
                "before_hash": hashed(previous),
                "after_hash": hashed(current),
                "before_version": previous.get("version"),
                "after_version": current.get("version"),
                "changed_fields": sorted(
                    key
                    for key in previous.keys() | current.keys()
                    if previous.get(key) != current.get(key)
                ),
                **trace_metadata(),
            },
            created_at=datetime.now(UTC),
        )
    )
