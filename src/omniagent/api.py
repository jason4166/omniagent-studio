import os
from collections.abc import Iterator
from typing import Annotated

from fastapi import Depends, FastAPI, File, Request, Response, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from omniagent.database import build_engine, build_session_factory
from omniagent.embeddings import FakeEmbedding
from omniagent.ingestion import SourceImportResult
from omniagent.postgres_repositories import (
    SqlAlchemyAgentProfileRepository,
    SqlAlchemyKnowledgeRepository,
)
from omniagent.profiles import AgentProfile, AgentProfilePatch, KnowledgeBase
from omniagent.repositories import InMemoryAgentProfileRepository, InMemoryKnowledgeRepository
from omniagent.services import (
    AgentProfileAlreadyExistsError,
    AgentProfileNotFoundError,
    AgentProfileService,
    AgentProfileVersionConflictError,
    KnowledgeBaseAlreadyExistsError,
    KnowledgeBaseNotFoundError,
    KnowledgeBaseService,
)


class ErrorDetail(BaseModel):
    code: str
    message: str


class ErrorResponse(BaseModel):
    error: ErrorDetail


app = FastAPI()


@app.exception_handler(AgentProfileAlreadyExistsError)
def handle_agent_already_exists(
    _request: Request,
    exc: AgentProfileAlreadyExistsError,
) -> JSONResponse:
    return JSONResponse(
        status_code=409,
        content={
            "error": {
                "code": "agent_already_exists",  # 固定机器码
                "message": str(exc),  # 从异常中读取消息
            }
        },
    )


_memory_profile_repository = InMemoryAgentProfileRepository()
_memory_knowledge_repository = InMemoryKnowledgeRepository()
_database_url = os.environ.get("OMNIAGENT_DATABASE_URL")
_database_engine = build_engine(_database_url) if _database_url else None
_database_session_factory = (
    build_session_factory(_database_engine) if _database_engine is not None else None
)
_embedding_provider = FakeEmbedding()


@app.exception_handler(AgentProfileVersionConflictError)
def handle_agent_version_conflict(
    _request: Request,
    exc: AgentProfileVersionConflictError,
) -> JSONResponse:
    return JSONResponse(
        status_code=409,
        content={
            "error": {
                "code": "agent_version_conflict",  # 固定机器码
                "message": str(exc),  # 从异常中读取消息
            }
        },
    )


@app.exception_handler(RequestValidationError)
def handle_request_validation_error(
    _request: Request,
    exc: RequestValidationError,
) -> JSONResponse:
    return JSONResponse(
        status_code=422,
        content={
            "error": {
                "code": "request_validation_error",
                "message": "Request validation failed",
            }
        },
    )


@app.exception_handler(AgentProfileNotFoundError)
def handle_agent_not_found(
    _request: Request,
    exc: AgentProfileNotFoundError,
) -> JSONResponse:
    return JSONResponse(
        status_code=404,  # 资源不存在
        content={
            "error": {
                "code": "agent_not_found",
                "message": str(exc),
            }
        },
    )


@app.exception_handler(KnowledgeBaseAlreadyExistsError)
def handle_knowledge_base_already_exists(
    _request: Request,
    exc: KnowledgeBaseAlreadyExistsError,
) -> JSONResponse:
    return JSONResponse(
        status_code=409,
        content={
            "error": {
                "code": "knowledge_base_already_exists",
                "message": str(exc),
            }
        },
    )


@app.exception_handler(KnowledgeBaseNotFoundError)
def handle_knowledge_base_not_found(
    _request: Request,
    exc: KnowledgeBaseNotFoundError,
) -> JSONResponse:
    return JSONResponse(
        status_code=404,
        content={
            "error": {
                "code": "knowledge_base_not_found",
                "message": str(exc),
            }
        },
    )


def get_database_session() -> Iterator[Session | None]:
    if _database_session_factory is None:
        yield None
        return

    with _database_session_factory.begin() as session:
        yield session


def get_agent_profile_service(
    session: Annotated[
        Session | None,
        Depends(get_database_session),
    ],
) -> AgentProfileService:
    if session is None:
        return AgentProfileService(_memory_profile_repository)

    return AgentProfileService(SqlAlchemyAgentProfileRepository(session))


def get_knowledge_base_service(
    session: Annotated[
        Session | None,
        Depends(get_database_session),
    ],
) -> KnowledgeBaseService:
    if session is None:
        return KnowledgeBaseService(_memory_knowledge_repository)

    return KnowledgeBaseService(
        SqlAlchemyKnowledgeRepository(
            session,
            _embedding_provider,
        )
    )


@app.get(
    "/api/agents/{profile_id}",
    response_model=AgentProfile,
    responses={
        404: {
            "model": ErrorResponse,
            "description": "Agent profile not found",
        },
        422: {
            "model": ErrorResponse,
            "description": "Request validation failed",
        },
    },
)
def get_agent(
    profile_id: str,
    service: Annotated[
        AgentProfileService,
        Depends(get_agent_profile_service),
    ],
) -> AgentProfile:
    return service.get(profile_id)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post(
    "/api/agents",
    status_code=201,
    response_model=AgentProfile,
    responses={
        409: {
            "model": ErrorResponse,
            "description": "Agent profile already exists",
        },
        422: {
            "model": ErrorResponse,
            "description": "Request validation failed",
        },
    },
)
def create_agent(
    profile: AgentProfile,
    service: Annotated[
        AgentProfileService,
        Depends(get_agent_profile_service),
    ],
) -> AgentProfile:
    return service.create(profile)


@app.patch(
    "/api/agents/{profile_id}",
    response_model=AgentProfile,
    responses={
        404: {
            "model": ErrorResponse,
            "description": "Agent profile not found",
        },
        409: {
            "model": ErrorResponse,
            "description": "Agent profile version conflict",
        },
        422: {
            "model": ErrorResponse,
            "description": "Request validation failed",
        },
    },
)
def update_agent(
    profile_id: str,
    patch: AgentProfilePatch,
    service: Annotated[
        AgentProfileService,
        Depends(get_agent_profile_service),
    ],
) -> AgentProfile:
    return service.update(profile_id, patch)


@app.post(
    "/api/knowledge-bases",
    status_code=201,
    response_model=KnowledgeBase,
    responses={
        409: {
            "model": ErrorResponse,
            "description": "Knowledge base already exists",
        },
        422: {
            "model": ErrorResponse,
            "description": "Request validation failed",
        },
    },
)
def create_knowledge_base(
    knowledge_base: KnowledgeBase,
    service: Annotated[
        KnowledgeBaseService,
        Depends(get_knowledge_base_service),
    ],
) -> KnowledgeBase:
    return service.create(knowledge_base)


@app.post(
    "/api/knowledge-bases/{knowledge_base_id}/sources",
    response_model=SourceImportResult,
    responses={
        404: {
            "model": ErrorResponse,
            "description": "Knowledge base not found",
        },
        413: {
            "model": SourceImportResult,
            "description": "Upload is too large",
        },
        415: {
            "model": SourceImportResult,
            "description": "Unsupported file type",
        },
        422: {
            "model": SourceImportResult,
            "description": "Document cannot be imported",
        },
    },
)
async def upload_knowledge_source(
    knowledge_base_id: str,
    response: Response,
    file: Annotated[UploadFile, File()],
    service: Annotated[
        KnowledgeBaseService,
        Depends(get_knowledge_base_service),
    ],
) -> SourceImportResult:
    raw_bytes = await file.read(KnowledgeBaseService.MAX_UPLOAD_BYTES + 1)
    result = service.import_source(
        knowledge_base_id=knowledge_base_id,
        source_name=file.filename or "",
        mime_type=file.content_type or "",
        raw_bytes=raw_bytes,
    )

    if result.status == "imported":
        response.status_code = 201
    elif result.status in {"duplicate", "rebuilt"}:
        response.status_code = 200
    elif result.error is not None and result.error.code == "upload_too_large":
        response.status_code = 413
    elif result.status == "rejected":
        response.status_code = 415
    else:
        response.status_code = 422

    return result
