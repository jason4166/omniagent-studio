"""Local business HTTP service. Writes additionally verify the approval ledger."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import FastAPI, Header, HTTPException, Request
from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError

from omniagent.database import build_engine, configured_database_url
from omniagent.demo_data import business_schemas, read_business
from omniagent.execution import IdempotentMockAdapter, execution_key
from omniagent.session_models import SessionData
from omniagent.session_rows import ApprovalRow, SessionRow
from omniagent.session_store import SessionStore, digest
from omniagent.tooling import ToolBusinessError


def create_mock_app(database_url: str | None = None) -> FastAPI:
    url = database_url or configured_database_url("")
    store = SessionStore(build_engine(url))

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        yield
        store.engine.dispose()

    app = FastAPI(title="OmniAgent synthetic mock service", lifespan=lifespan)
    schemas = business_schemas()

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/tools/{operation}")
    def read(operation: str, request: Request) -> dict[str, object]:
        if operation not in {"lookup_product", "check_warranty", "lookup_customer"}:
            raise HTTPException(404, "Unknown read operation")
        arguments: dict[str, object] = dict(request.query_params)
        try:
            Draft202012Validator(schemas[operation]).validate(arguments)
            return read_business(operation, arguments)
        except ValidationError as exc:
            raise HTTPException(422, "Invalid business parameters") from exc
        except ToolBusinessError as exc:
            raise HTTPException(404, "Record not found") from exc

    @app.post("/tools/{operation}")
    def write(
        operation: str,
        arguments: dict[str, object],
        idempotency_key: Annotated[str | None, Header()] = None,
    ) -> object:
        if operation not in {"create_followup", "request_discount"}:
            raise HTTPException(404, "Unknown write operation")
        try:
            Draft202012Validator(schemas[operation]).validate(arguments)
        except ValidationError as exc:
            raise HTTPException(422, "Invalid business parameters") from exc
        if not idempotency_key:
            raise HTTPException(403, "Server execution identity required")
        with store.factory() as db:
            approval = db.get(ApprovalRow, idempotency_key)
            if (
                approval is None
                or approval.status not in ("approved", "executed")
                or approval.tool_name != operation
                or approval.decision_key is None
                or digest(approval.arguments) != digest(arguments)
            ):
                raise HTTPException(403, "Approved payload required")
            session = db.get(SessionRow, approval.thread_id)
            if session is None:
                raise HTTPException(403, "Active session required")
            state = SessionData.model_validate(session.data)
            if (
                state.run_id != approval.run_id
                or state.status not in ("running", "completed")
                or state.usage.tool_calls < 1
                or session.expires_at.timestamp() <= store.clock()
            ):
                raise HTTPException(403, "Execution reservation required")
        token = execution_key.set(idempotency_key)
        try:
            return IdempotentMockAdapter(store, operation).execute(arguments)
        finally:
            execution_key.reset(token)

    return app
