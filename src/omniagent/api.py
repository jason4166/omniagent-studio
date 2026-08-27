from typing import Annotated

from fastapi import Depends, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from omniagent.profiles import AgentProfile, AgentProfilePatch
from omniagent.repositories import InMemoryAgentProfileRepository
from omniagent.services import (
    AgentProfileAlreadyExistsError,
    AgentProfileNotFoundError,
    AgentProfileService,
    AgentProfileVersionConflictError,
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


_repository = InMemoryAgentProfileRepository()


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


def get_agent_profile_service() -> AgentProfileService:
    return AgentProfileService(_repository)


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
