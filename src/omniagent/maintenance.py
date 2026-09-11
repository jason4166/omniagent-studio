"""Explicit retention maintenance; never available to the model or public HTTP API."""

from datetime import UTC, datetime

from sqlalchemy import delete, select

from omniagent.access_rows import LoginRow, QuotaRow, StreamLeaseRow
from omniagent.checkpoints import postgres_saver
from omniagent.database import build_engine
from omniagent.errors import ErrorCode, PlatformError
from omniagent.semantic_cache import SemanticCacheRow
from omniagent.session_rows import SessionRow
from omniagent.session_store import SessionStore


def purge(database_url: str, *, batch: int = 100) -> dict[str, int]:
    if not 1 <= batch <= 1000:
        raise ValueError("Retention batches must contain 1..1000 sessions")
    store = SessionStore(build_engine(database_url))
    now = datetime.now(UTC)
    removed, busy = 0, 0
    try:
        with store.factory() as db:
            expired = list(
                db.scalars(
                    select(SessionRow.thread_id)
                    .where(SessionRow.expires_at <= now)
                    .order_by(SessionRow.expires_at)
                    .limit(batch)
                )
            )
        with postgres_saver(database_url) as saver:
            for thread_id in expired:
                try:
                    with store.lock(thread_id), store.factory.begin() as db:
                        row = db.get(SessionRow, thread_id)
                        if row is None or row.expires_at > now:
                            continue
                        saver.delete_thread(thread_id)
                        db.execute(delete(SessionRow).where(SessionRow.thread_id == thread_id))
                        removed += 1
                except PlatformError as exc:
                    if exc.code != ErrorCode.CONFLICT:
                        raise
                    busy += 1
        with store.factory.begin() as db:
            db.execute(delete(SemanticCacheRow).where(SemanticCacheRow.expires_at <= now))
            for model in (LoginRow, QuotaRow, StreamLeaseRow):
                db.execute(delete(model).where(model.expires_at <= now))
        return {"expired_sessions_deleted": removed, "busy_sessions_skipped": busy}
    finally:
        store.engine.dispose()
