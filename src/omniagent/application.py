"""Public v1 application factory: database-backed configuration and one execution API."""

import os
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager, contextmanager
from typing import Annotated, Literal

from fastapi import Depends, FastAPI, File, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import delete, select, text
from sqlalchemy.exc import SQLAlchemyError

from omniagent.access import AccessService, build_access_router
from omniagent.access_config import AccessSettings
from omniagent.checkpoints import postgres_saver
from omniagent.connectors import build_adapters, build_registry, catalog, validate_definition
from omniagent.credentials import secret_configured
from omniagent.database import build_engine, configured_database_url
from omniagent.db_models import (
    AgentProfileRow,
    ChunkRow,
    KnowledgeBaseRow,
    SourceRow,
    ToolDefinitionRow,
)
from omniagent.durable_runtime import DurableRuntime
from omniagent.embedding_config import EmbeddingConfiguration
from omniagent.embeddings import embedding_identity
from omniagent.errors import ErrorCode, PlatformError
from omniagent.events import build_event_router
from omniagent.http_tools import import_openapi_subset
from omniagent.identity import DevUserContext
from omniagent.ingestion import SourceImportResult
from omniagent.llm import LLMProvider
from omniagent.metered_embedding import MeteredEmbedding
from omniagent.middleware import BoundaryMiddleware, RateLimiter
from omniagent.postgres_repositories import (
    SqlAlchemyAgentProfileRepository,
    SqlAlchemyKnowledgeRepository,
    SqlAlchemyPromptVersionRepository,
    SqlAlchemyToolDefinitionRepository,
)
from omniagent.postgres_retrieval import HybridRetriever
from omniagent.profiles import AgentProfile, KnowledgeBase, PromptVersion
from omniagent.prompts import PromptVersionAlreadyExistsError, PromptVersionService
from omniagent.providers import configured_provider
from omniagent.redaction import contains_secret
from omniagent.reliability import CircuitBreaker
from omniagent.semantic_cache import SemanticRetriever
from omniagent.services import (
    KnowledgeBaseAlreadyExistsError,
    KnowledgeBaseNotFoundError,
    KnowledgeBaseService,
)
from omniagent.session_api import User, build_session_router, current_user
from omniagent.session_rows import AuditRow, SessionRow
from omniagent.session_store import SessionStore
from omniagent.telemetry import Telemetry
from omniagent.tooling import ToolDefinition

DEFAULT_DATABASE_URL = (
    "postgresql+psycopg://omniagent:omniagent-local-only@127.0.0.1:55432/omniagent_v1_test"
)


def administrator(actor: Annotated[DevUserContext, Depends(current_user)]) -> DevUserContext:
    if actor.role != "admin":
        raise PlatformError(ErrorCode.PERMISSION)
    return actor


Admin = Annotated[DevUserContext, Depends(administrator)]


class ProfileUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_version: int = Field(ge=1)
    profile: AgentProfile


class ProfileBundle(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal[1] = 1
    profile: AgentProfile


class CreatePrompt(BaseModel):
    model_config = ConfigDict(extra="forbid")
    prompt_version_id: str = Field(min_length=1, max_length=120)
    content: str = Field(min_length=1, max_length=6000)


def create_app(
    database_url: str | None = None,
    *,
    provider: LLMProvider | None = None,
    mock_host: str | None = None,
    mock_port: int | None = None,
    rate_limit: int | None = None,
    cache_enabled: bool | None = None,
) -> FastAPI:
    url = database_url or configured_database_url(DEFAULT_DATABASE_URL)
    host = mock_host or os.environ.get("OMNIAGENT_MOCK_HOST", "127.0.0.1")
    port = mock_port or int(os.environ.get("OMNIAGENT_MOCK_PORT", "18081"))
    if host not in {"127.0.0.1", "mock"}:
        raise ValueError("Only the fixed local mock connector is enabled in v1")
    store = SessionStore(build_engine(url))
    access = AccessService(store, AccessSettings.from_environment(url))
    embedding_configuration = EmbeddingConfiguration.from_environment()
    baselines, approved_http = catalog(host, port)
    adapters = build_adapters(host, port)
    telemetry = Telemetry(
        enabled=os.environ.get("OMNIAGENT_TELEMETRY", "on") != "off", configure_export=True
    )
    circuits = {name: CircuitBreaker() for name in ("fake", "primary", "secondary")}

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        yield
        store.engine.dispose()
        telemetry.shutdown()

    app = FastAPI(
        title="OmniAgent Studio",
        version="1.0.0-rc.3",
        lifespan=lifespan,
        docs_url=None if access.settings.production else "/docs",
        redoc_url=None,
        openapi_url=None if access.settings.production else "/openapi.json",
    )
    app.state.store = store
    app.state.access = access
    app.state.telemetry = telemetry
    app.add_middleware(
        BoundaryMiddleware,
        telemetry=telemetry,
        access=access,
        limiter=RateLimiter(
            limit=rate_limit or int(os.environ.get("OMNIAGENT_RATE_LIMIT_PER_MINUTE", "240"))
        ),
    )
    app.include_router(build_access_router(access))

    @app.exception_handler(PlatformError)
    def platform_error(_request: Request, exc: PlatformError) -> JSONResponse:
        return JSONResponse(
            {"error": {"code": exc.code.value, "message": exc.message}}, status_code=exc.status_code
        )

    @app.exception_handler(RequestValidationError)
    @app.exception_handler(ValidationError)
    def validation_error(_request: Request, _exc: Exception) -> JSONResponse:
        return JSONResponse(
            {"error": {"code": "validation_error", "message": "Invalid request fields"}},
            status_code=422,
        )

    @app.exception_handler(SQLAlchemyError)
    def database_error(_request: Request, _exc: Exception) -> JSONResponse:
        return JSONResponse(
            {"error": {"code": "dependency_unavailable", "message": "Database unavailable"}},
            status_code=503,
        )

    @app.exception_handler(KnowledgeBaseNotFoundError)
    def missing_knowledge(_request: Request, _exc: Exception) -> JSONResponse:
        return JSONResponse(
            {"error": {"code": "not_found", "message": "Knowledge base not found"}}, status_code=404
        )

    @contextmanager
    def runtime(actor: DevUserContext, profile: AgentProfile) -> Iterator[DurableRuntime]:
        with configured_provider(profile, provider, circuits) as active:
            with postgres_saver(url) as saver, embedding_configuration.configured() as embedding:
                registry = build_registry(store, adapters, baselines)
                yield DurableRuntime(
                    store,
                    saver,
                    actor,
                    active,
                    registry,
                    SemanticRetriever(
                        store,
                        profile,
                        actor,
                        registry,
                        HybridRetriever(
                            store.factory,
                            MeteredEmbedding(embedding, access, actor),
                            text_query_operator="or",
                        ),
                        embedding_version=embedding_configuration.version,
                        embedding_model=embedding_identity(embedding),
                        enabled=cache_enabled
                        if cache_enabled is not None
                        else os.environ.get("OMNIAGENT_SEMANTIC_CACHE", "on") != "off",
                    ),
                    reserve_external=lambda tokens: access.reserve_model(actor, tokens),
                    validate_actor=lambda: access.validate_actor(actor),
                )

    def erase(thread_id: str, actor: DevUserContext) -> None:
        with store.lock(thread_id), store.factory.begin() as db:
            row = db.get(SessionRow, thread_id)
            if row is None or row.user_id != actor.user_id:
                raise PlatformError(ErrorCode.NOT_FOUND)
            with postgres_saver(url) as saver:
                saver.delete_thread(thread_id)
            db.execute(delete(SessionRow).where(SessionRow.thread_id == thread_id))

    app.include_router(build_session_router(store, runtime, erase))
    app.include_router(build_event_router(store))

    def validate_profile(profile: AgentProfile) -> None:
        if (
            profile.provider_id not in {"fake", "primary", "primary-with-fallback"}
            or profile.approval_policy_id != "safe-default"
        ):
            raise PlatformError(ErrorCode.VALIDATION, "Unknown provider or approval policy")
        if contains_secret(profile.model_dump_json()):
            raise PlatformError(
                ErrorCode.VALIDATION, "Configuration accepts credential references only"
            )
        with store.factory() as db:
            prompt = SqlAlchemyPromptVersionRepository(db).get(profile.prompt_version_id)
            if prompt is None or prompt.variables:
                raise PlatformError(ErrorCode.VALIDATION, "A static PromptVersion is required")
            for tool_id in profile.tool_ids:
                definition = SqlAlchemyToolDefinitionRepository(db).get(tool_id)
                if definition is None:
                    raise PlatformError(ErrorCode.VALIDATION, "Unknown tool reference")
                validate_definition(definition, baselines)
            if any(db.get(KnowledgeBaseRow, kb_id) is None for kb_id in profile.knowledge_base_ids):
                raise PlatformError(ErrorCode.VALIDATION, "Unknown knowledge base reference")

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/ready")
    def ready() -> dict[str, str]:
        with store.engine.connect() as connection:
            connection.execute(text("SELECT 1 FROM sessions LIMIT 1"))
            connection.execute(text("SELECT 1 FROM checkpoints LIMIT 1"))
            connection.execute(text("SELECT 1 FROM accounts LIMIT 1"))
            if access.settings.production:
                privileged = connection.scalar(
                    text(
                        "SELECT rolsuper OR rolcreatedb OR rolcreaterole "
                        "FROM pg_roles WHERE rolname = current_user"
                    )
                )
                if privileged:
                    raise PlatformError(
                        ErrorCode.UNAVAILABLE, "Runtime database role is overprivileged"
                    )
        return {"status": "ready"}

    @app.get("/api/profiles")
    def list_profiles(actor: User) -> list[AgentProfile]:
        with store.factory() as db:
            profiles = SqlAlchemyAgentProfileRepository(db).list_all()
        return [
            p
            for p in profiles
            if actor.role == "admin"
            or (p.profile_id in actor.profile_ids and p.enabled and actor.role in p.allowed_roles)
        ]

    @app.post("/api/profiles/validate")
    def validate(profile: AgentProfile, _actor: Admin) -> dict[str, bool]:
        validate_profile(profile)
        return {"valid": True}

    @app.post("/api/profiles", status_code=201)
    def create_profile(profile: AgentProfile, _actor: Admin) -> AgentProfile:
        validate_profile(profile)
        with store.factory.begin() as db:
            repository = SqlAlchemyAgentProfileRepository(db)
            if repository.get(profile.profile_id):
                raise PlatformError(ErrorCode.CONFLICT)
            profile = profile.model_copy(update={"version": 1})
            repository.save(profile)
        return profile

    @app.post("/api/profiles/import", status_code=201)
    def import_profile(bundle: ProfileBundle, actor: Admin) -> AgentProfile:
        return create_profile(bundle.profile, actor)

    @app.get("/api/profiles/{profile_id}/export")
    def export_profile(profile_id: str, actor: Admin) -> ProfileBundle:
        return ProfileBundle(profile=store.profile(profile_id, actor))

    @app.get("/api/profiles/{profile_id}")
    def get_profile(profile_id: str, actor: User) -> AgentProfile:
        return store.profile(profile_id, actor)

    @app.put("/api/profiles/{profile_id}")
    def update_profile(profile_id: str, payload: ProfileUpdate, _actor: Admin) -> AgentProfile:
        if payload.profile.profile_id != profile_id:
            raise PlatformError(ErrorCode.VALIDATION)
        validate_profile(payload.profile)
        with store.factory.begin() as db:
            row = db.scalar(
                select(AgentProfileRow)
                .where(AgentProfileRow.profile_id == profile_id)
                .with_for_update()
            )
            if row is None:
                raise PlatformError(ErrorCode.NOT_FOUND)
            if row.version != payload.expected_version:
                raise PlatformError(ErrorCode.CONFLICT)
            updated = payload.profile.model_copy(update={"version": row.version + 1})
            SqlAlchemyAgentProfileRepository(db).save(updated)
        return updated

    @app.get("/api/knowledge-bases")
    def knowledge_bases(_actor: Admin) -> list[KnowledgeBase]:
        with store.factory() as db:
            return [
                KnowledgeBase(knowledge_base_id=row.knowledge_base_id, name=row.name)
                for row in db.scalars(select(KnowledgeBaseRow).order_by(KnowledgeBaseRow.name))
            ]

    @app.post("/api/knowledge-bases", status_code=201)
    def create_knowledge(payload: KnowledgeBase, _actor: Admin) -> KnowledgeBase:
        with store.factory.begin() as db, embedding_configuration.configured() as embedding:
            try:
                return KnowledgeBaseService(SqlAlchemyKnowledgeRepository(db, embedding)).create(
                    payload
                )
            except KnowledgeBaseAlreadyExistsError as exc:
                raise PlatformError(ErrorCode.CONFLICT) from exc

    @app.get("/api/knowledge-bases/{kb_id}/sources")
    def sources(kb_id: str, _actor: Admin) -> list[dict[str, object]]:
        with store.factory() as db:
            return [
                {
                    "source_id": row.source_id,
                    "source_name": row.source_name,
                    "title": row.title,
                    "status": "indexed",
                    "checksum": row.checksum,
                }
                for row in db.scalars(select(SourceRow).where(SourceRow.knowledge_base_id == kb_id))
            ]

    @app.post("/api/knowledge-bases/{kb_id}/sources")
    def upload(
        kb_id: str, _actor: Admin, file: Annotated[UploadFile, File()]
    ) -> SourceImportResult:
        raw = file.file.read(KnowledgeBaseService.MAX_UPLOAD_BYTES + 1)
        if access.settings.mode != "dev":
            access.reserve(
                [("uploads:global", 1, 100), ("upload-bytes:global", max(1, len(raw)), 20000000)]
            )
        with store.factory.begin() as db, embedding_configuration.configured() as embedding:
            knowledge = SqlAlchemyKnowledgeRepository(
                db, MeteredEmbedding(embedding, access, _actor)
            )
            knowledge.validate_embedding_model([kb_id])
            return KnowledgeBaseService(knowledge).import_source(
                knowledge_base_id=kb_id,
                source_name=file.filename or "document.txt",
                mime_type=file.content_type or "text/plain",
                raw_bytes=raw,
            )

    @app.get("/api/sessions/{thread_id}/citations/{chunk_id}")
    def citation(thread_id: str, chunk_id: str, actor: User) -> dict[str, object]:
        _, profile = store.load_authorized(thread_id, actor)
        with store.factory() as db:
            row = db.scalar(
                select(ChunkRow).where(
                    ChunkRow.chunk_id == chunk_id,
                    ChunkRow.knowledge_base_id.in_(profile.knowledge_base_ids),
                )
            )
            if row is None:
                raise PlatformError(ErrorCode.NOT_FOUND)
            return {
                "chunk_id": row.chunk_id,
                "source_id": row.source_id,
                "knowledge_base_id": row.knowledge_base_id,
                "content": row.content,
                "metadata": row.chunk_metadata,
            }

    @app.get("/api/tools")
    def tools(_actor: Admin) -> list[dict[str, object]]:
        with store.factory() as db:
            return [
                tool.model_dump(mode="json")
                for tool in SqlAlchemyToolDefinitionRepository(db).list_all()
            ]

    @app.put("/api/tools/{tool_id}")
    def save_tool(tool_id: str, payload: ToolDefinition, _actor: Admin) -> ToolDefinition:
        definition = payload
        if definition.name != tool_id:
            raise PlatformError(ErrorCode.VALIDATION)
        validate_definition(definition, baselines)
        with store.factory.begin() as db:
            row = db.scalar(
                select(ToolDefinitionRow)
                .where(ToolDefinitionRow.tool_id == tool_id)
                .with_for_update()
            )
            if row is not None:
                existing = SqlAlchemyToolDefinitionRepository(db).get(tool_id)
                if existing is None or definition.version != existing.version:
                    raise PlatformError(ErrorCode.CONFLICT)
                definition.version += 1
            SqlAlchemyToolDefinitionRepository(db).save(definition)
        return definition

    @app.post("/api/tools/import-openapi")
    def import_tools(document: dict[str, object], _actor: Admin) -> list[ToolDefinition]:
        try:
            imported = import_openapi_subset(document, approved_http)
        except ValueError as exc:
            raise PlatformError(
                ErrorCode.VALIDATION, "Specification exceeds the approved subset"
            ) from exc
        result: list[ToolDefinition] = []
        with store.factory.begin() as db:
            repository = SqlAlchemyToolDefinitionRepository(db)
            for definition in baselines:
                if definition.name not in imported:
                    continue
                existing = repository.get(definition.name)
                if existing is None:
                    repository.save(definition)
                result.append(existing or definition)
        return result

    @app.get("/api/prompts")
    def prompts(_actor: Admin) -> list[PromptVersion]:
        from omniagent.db_models import PromptVersionRow

        with store.factory() as db:
            repository = SqlAlchemyPromptVersionRepository(db)
            result = [
                repository.get(key)
                for key in db.scalars(select(PromptVersionRow.prompt_version_id))
            ]
        return [prompt for prompt in result if prompt is not None]

    @app.post("/api/prompts", status_code=201)
    def create_prompt(payload: CreatePrompt, _actor: Admin) -> PromptVersion:
        from datetime import UTC, datetime

        if contains_secret(payload.content):
            raise PlatformError(ErrorCode.VALIDATION, "Prompt cannot contain credentials")
        with store.factory.begin() as db:
            try:
                return PromptVersionService(SqlAlchemyPromptVersionRepository(db)).create(
                    prompt_version_id=payload.prompt_version_id,
                    content=payload.content,
                    created_at=datetime.now(UTC),
                )
            except PromptVersionAlreadyExistsError as exc:
                raise PlatformError(ErrorCode.CONFLICT) from exc

    @app.get("/api/providers")
    def providers(_actor: Admin) -> list[dict[str, object]]:
        return [
            {"provider_id": "fake", "configured": True, "model": "fake-v1"},
            {
                "provider_id": "primary",
                "configured": secret_configured("OMNIAGENT_PROVIDER"),
                "model": os.environ.get("OMNIAGENT_PROVIDER_MODEL", "configured-model"),
            },
            {
                "provider_id": "primary-with-fallback",
                "configured": secret_configured("OMNIAGENT_PROVIDER")
                and secret_configured("OMNIAGENT_FALLBACK")
                and all(
                    os.environ.get(key)
                    for key in (
                        "OMNIAGENT_PROVIDER_BASE_URL",
                        "OMNIAGENT_FALLBACK_BASE_URL",
                        "OMNIAGENT_FALLBACK_MODEL",
                    )
                ),
                "model": "explicit primary + secondary",
            },
        ]

    @app.get("/api/runtime-info")
    def runtime_info(_actor: User) -> dict[str, object]:
        return {
            "embedding": {
                "provider": embedding_configuration.provider,
                "model": embedding_configuration.model,
                "dimension": 1024,
                "version": embedding_configuration.version,
            },
            "business_tools": "local-sandbox",
        }

    @app.get("/api/telemetry")
    def traces(_actor: Admin) -> list[dict[str, object]]:
        return telemetry.local.snapshot()[-200:]

    @app.get("/api/metrics")
    def metrics(_actor: Admin) -> dict[str, object]:
        return telemetry.metrics()

    @app.get("/api/audit")
    def audit(_actor: Admin) -> list[dict[str, object]]:
        with store.factory() as db:
            return [
                {
                    "audit_id": row.audit_id,
                    "actor_hash": row.actor_hash,
                    "thread_id": row.thread_id,
                    "run_id": row.run_id,
                    "action": row.action,
                    "details": row.details,
                    "created_at": row.created_at.isoformat(),
                }
                for row in db.scalars(
                    select(AuditRow).order_by(AuditRow.created_at.desc()).limit(100)
                )
            ]

    return app
