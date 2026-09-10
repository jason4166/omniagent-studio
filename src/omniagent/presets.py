"""Idempotent configuration and original synthetic knowledge seeding."""

import json
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import func, select

from omniagent.db_models import KnowledgeBaseRow, SourceRow
from omniagent.embeddings import FakeEmbedding
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
    store: SessionStore, definitions: list[ToolDefinition], directory: Path = Path("presets")
) -> dict[str, int]:
    configuration = json.loads((directory / "profiles.json").read_text(encoding="utf-8"))
    created = 0
    with store.factory.begin() as db:
        tools = SqlAlchemyToolDefinitionRepository(db)
        for definition in definitions:
            if tools.get(definition.name) is None:
                tools.save(definition)
        prompts = SqlAlchemyPromptVersionRepository(db)
        profiles = SqlAlchemyAgentProfileRepository(db)
        knowledge = SqlAlchemyKnowledgeRepository(db, FakeEmbedding())
        service = KnowledgeBaseService(knowledge)
        for entry in configuration:
            profile = AgentProfile.model_validate(entry["profile"])
            if prompts.get(profile.prompt_version_id) is None:
                PromptVersionService(prompts).create(
                    prompt_version_id=profile.prompt_version_id,
                    content=entry["prompt"]
                    + "\n<routing-config>"
                    + json.dumps(entry["routing_rules"], ensure_ascii=False)
                    + "</routing-config>",
                    created_at=datetime(2026, 9, 10, tzinfo=UTC),
                )
            for kb_id in profile.knowledge_base_ids:
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
