"""Idempotent configuration and original synthetic knowledge seeding."""

import json
import os
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import func, select

from omniagent.db_models import KnowledgeBaseRow, SourceRow
from omniagent.embedding_config import EmbeddingConfiguration
from omniagent.errors import ErrorCode, PlatformError
from omniagent.postgres_repositories import (
    SqlAlchemyAgentProfileRepository,
    SqlAlchemyKnowledgeRepository,
    SqlAlchemyPromptVersionRepository,
    SqlAlchemyToolDefinitionRepository,
)
from omniagent.profiles import AgentProfile, KnowledgeBase
from omniagent.prompts import PromptVersionService
from omniagent.services import KnowledgeBaseService
from omniagent.session_store import SessionStore
from omniagent.tooling import ToolDefinition


def seed(
    store: SessionStore,
    definitions: list[ToolDefinition],
    directory: Path = Path("presets"),
    *,
    mode: str = "fake",
) -> dict[str, int]:
    configuration = json.loads((directory / "profiles.json").read_text(encoding="utf-8"))
    if mode not in {"fake", "real"}:
        raise PlatformError(ErrorCode.VALIDATION, "Unknown seed mode")
    embedding_configuration = EmbeddingConfiguration.from_environment()
    if (mode == "real") != (embedding_configuration.provider == "primary"):
        raise PlatformError(
            ErrorCode.VALIDATION, "Seed mode must match the embedding configuration"
        )
    if mode == "real" and not os.environ.get("OMNIAGENT_PROVIDER_MODEL"):
        raise PlatformError(ErrorCode.VALIDATION, "Real seed requires an explicit chat model")
    created = 0
    with store.factory.begin() as db, embedding_configuration.configured() as embedding:
        tools = SqlAlchemyToolDefinitionRepository(db)
        for definition in definitions:
            if tools.get(definition.name) is None:
                tools.save(definition)
        prompts = SqlAlchemyPromptVersionRepository(db)
        profiles = SqlAlchemyAgentProfileRepository(db)
        knowledge = SqlAlchemyKnowledgeRepository(db, embedding)
        service = KnowledgeBaseService(knowledge)
        for entry in configuration:
            profile = AgentProfile.model_validate(entry["profile"])
            prompt_content = entry["prompt"]
            if mode == "real":
                profile = profile.model_copy(
                    update={
                        "provider_id": "primary",
                        "model": os.environ["OMNIAGENT_PROVIDER_MODEL"],
                        "prompt_version_id": profile.profile_id + ":real:v1",
                    }
                )
            else:
                prompt_content += (
                    "\n<routing-config>"
                    + json.dumps(entry["routing_rules"], ensure_ascii=False)
                    + "</routing-config>"
                )
            existing = profiles.get(profile.profile_id)
            if existing is not None and existing.provider_id != profile.provider_id:
                raise PlatformError(
                    ErrorCode.CONFLICT, "Use an isolated database for another seed mode"
                )
            if prompts.get(profile.prompt_version_id) is None:
                PromptVersionService(prompts).create(
                    prompt_version_id=profile.prompt_version_id,
                    content=prompt_content,
                    created_at=datetime(2026, 9, 10, tzinfo=UTC),
                )
            for kb_id in profile.knowledge_base_ids:
                knowledge.validate_embedding_model([kb_id])
                if knowledge.get_knowledge_base(kb_id) is None:
                    service.create(
                        KnowledgeBase(knowledge_base_id=kb_id, name=entry["knowledge_name"])
                    )
                for path in sorted((directory / "knowledge" / kb_id).glob("*.md")):
                    imported = service.import_source(
                        knowledge_base_id=kb_id,
                        source_name=path.name,
                        mime_type="text/markdown",
                        raw_bytes=path.read_bytes(),
                    )
                    if imported.status not in ("imported", "duplicate"):
                        raise RuntimeError("Preset ingestion failed")
            if profiles.get(profile.profile_id) is None:
                profiles.save(profile)
                created += 1
        db.flush()
        return {
            "created_profiles": created,
            "knowledge_bases": db.scalar(select(func.count()).select_from(KnowledgeBaseRow)) or 0,
            "sources": db.scalar(select(func.count()).select_from(SourceRow)) or 0,
        }
