"""Typed session endpoints. All execution enters the same durable runtime."""

from collections.abc import Callable
from contextlib import AbstractContextManager
from typing import Annotated

from fastapi import APIRouter, Depends, Header, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from omniagent.durable_runtime import DurableRuntime
from omniagent.errors import PlatformError
from omniagent.identity import DevUserContext, authenticate
from omniagent.profiles import AgentProfile
from omniagent.session_models import ApprovalDecision, SessionData
from omniagent.session_rows import SessionRow
from omniagent.session_store import SessionStore

RuntimeFactory = Callable[[DevUserContext, AgentProfile], AbstractContextManager[DurableRuntime]]


def current_user(authorization: Annotated[str | None, Header()] = None) -> DevUserContext:
    return authenticate(authorization)


User = Annotated[DevUserContext, Depends(current_user)]


class CreateSession(BaseModel):
    model_config = ConfigDict(extra="forbid")
    profile_id: str = Field(min_length=1, max_length=120)


class SendMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")
    message: str = Field(min_length=1, max_length=8000)
    request_key: str = Field(min_length=8, max_length=128, pattern=r"^[a-zA-Z0-9_-]+$")


def build_session_router(
    store: SessionStore,
    factory: RuntimeFactory,
    eraser: Callable[[str, DevUserContext], None] | None = None,
) -> APIRouter:
    router = APIRouter(prefix="/api/sessions", tags=["sessions"])

    def runtime(thread_id: str, actor: DevUserContext) -> AbstractContextManager[DurableRuntime]:
        _, profile = store.load_authorized(thread_id, actor)
        return factory(actor, profile)

    @router.post("", status_code=201)
    def create(payload: CreateSession, actor: User) -> SessionData:
        return store.create(payload.profile_id, actor)

    @router.get("")
    def list_sessions(actor: User) -> list[SessionData]:
        with store.factory() as db:
            rows = list(
                db.scalars(
                    select(SessionRow)
                    .where(
                        SessionRow.user_id == actor.user_id,
                    )
                    .order_by(SessionRow.expires_at.desc())
                    .limit(100)
                )
            )
            result: list[SessionData] = []
            for row in rows:
                try:
                    data = store.decode(row, actor)
                    store.profile(data.profile_id, actor)
                    result.append(data)
                except PlatformError:
                    continue
            return result

    @router.get("/{thread_id}")
    def get(thread_id: str, actor: User) -> SessionData:
        return store.load(thread_id, actor)

    @router.post("/{thread_id}/messages")
    def send(thread_id: str, payload: SendMessage, actor: User) -> SessionData:
        with runtime(thread_id, actor) as service:
            return service.send(thread_id, payload.message, payload.request_key)

    @router.post("/{thread_id}/resume")
    def resume(thread_id: str, actor: User) -> SessionData:
        with runtime(thread_id, actor) as service:
            return service.resume(thread_id)

    @router.post("/{thread_id}/cancel")
    def cancel(thread_id: str, actor: User) -> SessionData:
        with runtime(thread_id, actor) as service:
            return service.cancel(thread_id)

    @router.get("/{thread_id}/approvals/{approval_id}")
    def approval(thread_id: str, approval_id: str, actor: User) -> dict[str, object]:
        with runtime(thread_id, actor) as service:
            return service.approvals.get(thread_id, approval_id, actor)

    @router.post("/{thread_id}/approvals/{approval_id}")
    def decide(
        thread_id: str,
        approval_id: str,
        payload: ApprovalDecision,
        actor: User,
    ) -> SessionData:
        with runtime(thread_id, actor) as service:
            return service.decide(thread_id, approval_id, payload)

    @router.delete("/{thread_id}", status_code=204)
    def delete(thread_id: str, actor: User) -> Response:
        if eraser is not None:
            eraser(thread_id, actor)
            return Response(status_code=204)
        # Allow erasure after TTL without making expired state resumable.
        with store.factory() as db:
            row = db.get(SessionRow, thread_id)
            profile_id = row.profile_id if row is not None else ""
        with factory(actor, store.profile(profile_id, actor)) as service:
            service.delete(thread_id)
        return Response(status_code=204)

    return router
