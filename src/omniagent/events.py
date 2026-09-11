"""Authenticated, replay-only SSE. Subscribing never runs a graph or a tool."""

import json
from collections.abc import AsyncIterator
from time import monotonic
from typing import Annotated

import anyio
from fastapi import APIRouter, Header, Query, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import select

from omniagent.errors import ErrorCode, PlatformError
from omniagent.session_api import User
from omniagent.session_rows import EventRow, SessionRow
from omniagent.session_store import SessionStore


def parse_cursor(thread_id: str, after: int, last_event_id: str | None) -> int:
    if last_event_id is None:
        return after
    prefix, separator, raw = last_event_id.rpartition(":")
    if not separator or prefix != thread_id or not raw.isascii() or not raw.isdecimal():
        raise PlatformError(ErrorCode.VALIDATION, "Invalid event cursor")
    return max(after, int(raw))


def build_event_router(store: SessionStore) -> APIRouter:
    router = APIRouter(tags=["events"])

    @router.get("/api/sessions/{thread_id}/events")
    async def events(
        thread_id: str,
        actor: User,
        request: Request,
        after: Annotated[int, Query(ge=0, le=2147483647)] = 0,
        follow: bool = True,
        last_event_id: Annotated[str | None, Header(max_length=160)] = None,
    ) -> StreamingResponse:
        cursor = parse_cursor(thread_id, after, last_event_id)

        def read(position: int) -> list[dict[str, object]]:
            access = getattr(request.app.state, "access", None)
            if access is not None:
                access.revalidate(request)
            store.load(thread_id, actor)
            with store.factory() as db:
                session = db.get(SessionRow, thread_id)
                if session is None or position > session.sequence:
                    raise PlatformError(ErrorCode.VALIDATION, "Cursor is ahead of the event log")
                return [
                    {
                        "schema_version": 1,
                        "event_id": row.event_id,
                        "sequence": row.sequence,
                        "thread_id": row.thread_id,
                        "run_id": row.run_id,
                        "kind": row.kind,
                        "data": row.data,
                        "created_at": row.created_at.isoformat(),
                    }
                    for row in db.scalars(
                        select(EventRow)
                        .where(EventRow.thread_id == thread_id, EventRow.sequence > position)
                        .order_by(EventRow.sequence)
                        .limit(250)
                    )
                ]

        initial = await anyio.to_thread.run_sync(read, cursor)

        async def stream() -> AsyncIterator[str]:
            position = cursor
            batch = initial
            deadline = monotonic() + 45
            heartbeat = monotonic()
            while True:
                for event in batch:
                    position = int(str(event["sequence"]))
                    yield (
                        f"id: {event['event_id']}\nevent: {event['kind']}\n"
                        f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
                    )
                if not follow and len(batch) < 250:
                    return
                if await request.is_disconnected() or monotonic() >= deadline:
                    return
                if len(batch) < 250:
                    if monotonic() - heartbeat >= 10:
                        yield ": heartbeat\n\n"
                        heartbeat = monotonic()
                    await anyio.sleep(0.2)
                try:
                    batch = await anyio.to_thread.run_sync(read, position)
                except PlatformError as exc:
                    yield f"event: stream.closed\ndata: {json.dumps({'code': exc.code.value})}\n\n"
                    return

        return StreamingResponse(
            stream(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
        )

    return router
