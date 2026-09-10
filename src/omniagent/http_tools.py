"""A fixed-destination HTTP adapter; model data can only fill business fields."""

import ipaddress
import json
import os
import socket
from time import monotonic
from typing import Literal

import httpx
from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError
from pydantic import BaseModel, ConfigDict, Field, field_validator

from omniagent.execution import execution_key
from omniagent.tooling import ToolBusinessError


class HTTPConnectorConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    host: str
    port: int = Field(ge=1, le=65535)
    path: str = Field(pattern=r"^/[a-zA-Z0-9/_-]+$")
    method: Literal["GET", "POST"]
    headers: dict[str, str] = Field(default_factory=dict)
    secret_ref: str | None = Field(default=None, pattern=r"^OMNIAGENT_CONNECTOR_[A-Z0-9_]+$")
    timeout_seconds: float = Field(default=5, gt=0, le=30)
    max_response_bytes: int = Field(default=16000, ge=256, le=65536)
    parameters_schema: dict[str, object]
    output_schema: dict[str, object] = Field(default_factory=dict)

    @field_validator("host")
    @classmethod
    def valid_host(cls, value: str) -> str:
        if not value or any(character in value for character in "/\\:@%?#\r\n"):
            raise ValueError("Use a fixed hostname or IPv4 address")
        return value.lower()

    @field_validator("headers")
    @classmethod
    def safe_headers(cls, value: dict[str, str]) -> dict[str, str]:
        if any(
            key.lower() not in {"accept", "x-client-id"} or "\r" in item or "\n" in item
            for key, item in value.items()
        ):
            raise ValueError("Only fixed non-sensitive headers are supported")
        return value


class HTTPToolAdapter:
    def __init__(
        self,
        config: HTTPConnectorConfig,
        *,
        approved_origins: frozenset[tuple[str, int]],
        local_mock_hosts: frozenset[str] = frozenset(),
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        if (config.host, config.port) not in approved_origins:
            raise ValueError("HTTP origin is not administrator-approved")
        self.config = config
        self.transport = transport
        addresses = {
            str(item[4][0])
            for item in socket.getaddrinfo(config.host, config.port, type=socket.SOCK_STREAM)
        }
        if not addresses:
            raise ValueError("HTTP origin has no address")
        for value in addresses:
            address = ipaddress.ip_address(value)
            if (
                address.is_link_local
                or address.is_multicast
                or address.is_unspecified
                or (not address.is_global and config.host not in local_mock_hosts)
            ):
                raise ValueError("HTTP destination is forbidden")
        # The verified address is also the dialled address, preventing a second DNS lookup.
        self.address = sorted(addresses)[0]

    def execute(self, arguments: dict[str, object]) -> object:
        config = self.config
        try:
            Draft202012Validator(config.parameters_schema).validate(arguments)
        except ValidationError as exc:
            raise ToolBusinessError("invalid_arguments", "Business parameters are invalid") from exc
        headers = {
            **config.headers,
            "Host": f"{config.host}:{config.port}",
            "Accept": "application/json",
        }
        if config.secret_ref:
            secret = os.environ.get(config.secret_ref)
            if not secret:
                raise ToolBusinessError("connector_auth", "Connector credential is unavailable")
            headers["Authorization"] = "Bearer " + secret
        if config.method == "POST":
            key = execution_key.get()
            if key is None:
                raise ToolBusinessError("approval_required", "No server execution identity")
            headers["Idempotency-Key"] = key
        address = f"[{self.address}]" if ":" in self.address else self.address
        target = f"http://{address}:{config.port}{config.path}"
        headers["Accept-Encoding"] = "identity"
        deadline = monotonic() + config.timeout_seconds
        try:
            with httpx.Client(
                timeout=config.timeout_seconds,
                follow_redirects=False,
                trust_env=False,
                transport=self.transport,
            ) as client:
                with client.stream(
                    config.method,
                    target,
                    headers=headers,
                    params={key: str(value) for key, value in arguments.items()}
                    if config.method == "GET"
                    else None,
                    json=arguments if config.method == "POST" else None,
                ) as response:
                    if response.is_redirect:
                        raise ToolBusinessError("http_redirect", "Redirects are not permitted")
                    if response.headers.get("content-encoding", "identity") != "identity":
                        raise ToolBusinessError(
                            "http_encoding", "Compressed responses are unsupported"
                        )
                    if response.status_code >= 400:
                        raise ToolBusinessError(
                            f"http_{response.status_code}", "Connector request failed"
                        )
                    content_type = response.headers.get("content-type", "").split(";")[0].strip()
                    if content_type != "application/json":
                        raise ToolBusinessError("http_content_type", "Expected a JSON response")
                    raw = bytearray()
                    for block in response.iter_bytes(chunk_size=4096):
                        if monotonic() > deadline:
                            raise TimeoutError("Connector deadline exhausted")
                        raw.extend(block)
                        if len(raw) > config.max_response_bytes:
                            raise ToolBusinessError(
                                "http_response_size", "Connector response exceeded limit"
                            )
                    try:
                        result: object = json.loads(raw)
                        Draft202012Validator(config.output_schema).validate(result)
                    except (ValueError, ValidationError) as exc:
                        raise ToolBusinessError(
                            "http_bad_json", "Connector response failed validation"
                        ) from exc
                    return result
        except httpx.TimeoutException as exc:
            raise TimeoutError("Connector timed out") from exc
        except httpx.RequestError as exc:
            raise ToolBusinessError("http_unavailable", "Connector is unavailable") from exc


def import_openapi_subset(
    document: dict[str, object],
    approved: dict[str, HTTPConnectorConfig],
) -> dict[str, HTTPConnectorConfig]:
    """Only schema-identical, pre-approved operations can be imported; no remote references."""
    serialized = json.dumps(document)
    if len(serialized) > 65536 or "$ref" in serialized or document.get("servers"):
        raise ValueError("External servers, references or oversized specifications are unsupported")
    if not str(document.get("openapi", "")).startswith("3."):
        raise ValueError("Only the controlled OpenAPI 3 subset is supported")
    paths = document.get("paths")
    if not isinstance(paths, dict):
        raise ValueError("OpenAPI paths are required")
    result: dict[str, HTTPConnectorConfig] = {}
    for path, methods in paths.items():
        if not isinstance(methods, dict):
            raise ValueError("Invalid path item")
        for method, operation in methods.items():
            if not isinstance(operation, dict):
                raise ValueError("Invalid operation")
            operation_id = operation.get("operationId")
            if not isinstance(operation_id, str) or operation_id not in approved:
                raise ValueError("Unapproved operation")
            config = approved[operation_id]
            if config.path != path or config.method.lower() != method:
                raise ValueError("Operation destination mismatch")
            if method == "get":
                parameters = operation.get("parameters", [])
                if not isinstance(parameters, list):
                    raise ValueError("Invalid query parameters")
                fields: dict[str, object] = {}
                required: list[str] = []
                for parameter in parameters:
                    if (
                        not isinstance(parameter, dict)
                        or parameter.get("in") != "query"
                        or not isinstance(parameter.get("name"), str)
                        or not isinstance(parameter.get("schema"), dict)
                    ):
                        raise ValueError("Only fixed query parameters are supported")
                    name = parameter["name"]
                    if name in fields:
                        raise ValueError("Duplicate parameter")
                    fields[name] = parameter["schema"]
                    if parameter.get("required"):
                        required.append(name)
                schema = {
                    "type": "object",
                    "properties": fields,
                    "required": required,
                    "additionalProperties": False,
                }
            else:
                body = operation.get("requestBody", {})
                if not isinstance(body, dict) or not body.get("required"):
                    raise ValueError("A required JSON body is needed")
                content = body.get("content", {})
                if not isinstance(content, dict) or set(content) != {"application/json"}:
                    raise ValueError("Only JSON bodies are supported")
                schema = content["application/json"].get("schema")
            if schema != config.parameters_schema:
                raise ValueError("Business schema mismatch")
            if set(operation) - {
                "operationId",
                "summary",
                "responses",
                "parameters",
                "requestBody",
            }:
                raise ValueError("Unsupported operation fields")
            if operation_id in result:
                raise ValueError("Duplicate operation ID")
            result[operation_id] = config
    return result
