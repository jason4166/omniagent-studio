"""Fixed, read-only prerequisites and immutable bindings for a configured write proposal."""

from hashlib import sha256

from sqlalchemy import select
from sqlalchemy.orm import Session

from omniagent.db_models import ChunkRow, SourceRow
from omniagent.errors import ErrorCode, PlatformError
from omniagent.grounding import ContextPack
from omniagent.postgres_repositories import (
    SqlAlchemyKnowledgeRepository,
    SqlAlchemyToolDefinitionRepository,
)
from omniagent.profiles import AgentProfile, WritePreflightConfig
from omniagent.session_models import PreflightSnapshot, SessionData
from omniagent.session_store import SessionStore, digest
from omniagent.tool_registry import ToolRegistry
from omniagent.tooling import ToolRisk


def validate_preflight_configuration(profile: AgentProfile, registry: ToolRegistry) -> None:
    configuration = profile.write_preflight
    if configuration is None:
        return
    read = registry.definition(configuration.read_tool)
    write = registry.definition(configuration.write_tool)
    if (
        read is None
        or write is None
        or read.effect != "read"
        or read.risk is not ToolRisk.LOW
        or read.requires_approval
        or write.effect != "write"
        or not profile.auto_approve_read
    ):
        raise PlatformError(
            ErrorCode.VALIDATION, "Preflight requires a low-risk read and a write tool"
        )
    read_properties = read.parameters_schema.get("properties", {})
    write_properties = write.parameters_schema.get("properties", {})
    required = read.parameters_schema.get("required", [])
    if (
        not isinstance(read_properties, dict)
        or not isinstance(write_properties, dict)
        or not isinstance(required, list)
        or not set(required) <= set(configuration.argument_map) <= set(read_properties)
        or not set(configuration.argument_map.values()) <= set(write_properties)
    ):
        raise PlatformError(
            ErrorCode.VALIDATION, "Preflight argument mapping must match tool schemas"
        )


def mapped_read_arguments(
    configuration: WritePreflightConfig, arguments: dict[str, object]
) -> dict[str, object]:
    if any(field not in arguments for field in configuration.argument_map.values()):
        raise PlatformError(ErrorCode.VALIDATION, "Preflight identity arguments are missing")
    return {target: arguments[source] for target, source in configuration.argument_map.items()}


def policy_revisions(database: Session, pack: ContextPack) -> dict[str, str]:
    revisions = {}
    for item in pack.evidence:
        row = database.execute(
            select(ChunkRow, SourceRow)
            .join(SourceRow, SourceRow.source_id == ChunkRow.source_id)
            .where(ChunkRow.chunk_id == item.chunk_id)
        ).one_or_none()
        if row is None:
            raise PlatformError(ErrorCode.CONFLICT, "Preflight policy source is missing")
        chunk, source = row
        if (
            chunk.source_id != item.source_id
            or chunk.knowledge_base_id != item.knowledge_base_id
            or source.knowledge_base_id != item.knowledge_base_id
            or chunk.content != item.content
            or sha256(chunk.content.encode()).hexdigest() != item.content_sha256
            or SqlAlchemyKnowledgeRepository._build_source_locator(chunk) != item.source_locator
        ):
            raise PlatformError(ErrorCode.CONFLICT, "Preflight policy evidence changed")
        revisions[item.chunk_id] = digest(
            {
                "source_checksum": source.checksum,
                "source_content_hash": sha256(source.content.encode()).hexdigest(),
                "source_name": source.source_name,
                "chunk_index": chunk.chunk_index,
                "chunk": item.model_dump(mode="json"),
            }
        )
    return revisions


def require_preflight(
    profile: AgentProfile,
    registry: ToolRegistry,
    data: SessionData,
    name: str,
    arguments: dict[str, object],
    *,
    store: SessionStore,
    require_policy: bool = True,
) -> PreflightSnapshot | None:
    configuration = profile.write_preflight
    if configuration is None or configuration.write_tool != name:
        return None
    validate_preflight_configuration(profile, registry)
    read = registry.definition(configuration.read_tool)
    snapshot = data.preflight
    if (
        snapshot is None
        or snapshot.run_id != data.run_id
        or snapshot.profile_version != profile.version
        or snapshot.configuration_hash != digest(configuration.model_dump(mode="json"))
        or snapshot.write_tool != name
        or snapshot.read_tool != configuration.read_tool
        or snapshot.read_arguments != mapped_read_arguments(configuration, arguments)
        or read is None
        or not read.enabled
        or snapshot.read_policy_hash != digest(read.model_dump(mode="json"))
        or any(
            snapshot.read_result.get(key) != value for key, value in snapshot.read_arguments.items()
        )
    ):
        raise PlatformError(
            ErrorCode.CONFLICT, "Preflight inputs changed or are missing; start a new request"
        )
    if require_policy and (
        snapshot.policy_context is None
        or not snapshot.policy_context.evidence
        or any(
            item.knowledge_base_id not in profile.knowledge_base_ids
            for item in snapshot.policy_context.evidence
        )
    ):
        raise PlatformError(ErrorCode.PERMISSION, "Preflight requires authorized policy evidence")
    with store.factory() as database:
        if SqlAlchemyToolDefinitionRepository(database).get(snapshot.read_tool) != read:
            raise PlatformError(ErrorCode.CONFLICT, "Preflight read tool policy changed")
        if require_policy and snapshot.policy_context is not None:
            if policy_revisions(database, snapshot.policy_context) != snapshot.policy_revisions:
                raise PlatformError(ErrorCode.CONFLICT, "Preflight policy source revision changed")
    return snapshot
