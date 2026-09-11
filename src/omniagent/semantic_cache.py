"""Conservative query-normalized evidence cache, partitioned by policy and dependency version."""

import hashlib
import math
import os
import re
import unicodedata
from datetime import UTC, datetime, timedelta
from functools import lru_cache
from pathlib import Path

from pgvector.sqlalchemy import Vector
from pydantic import TypeAdapter, ValidationError
from sqlalchemy import DateTime, Integer, Text, delete, select
from sqlalchemy.dialects.postgresql import JSONB, insert
from sqlalchemy.orm import Mapped, mapped_column

from omniagent.chunking import ChunkMetadata
from omniagent.db_models import Base, ChunkRow, SourceRow
from omniagent.embedding_config import EmbeddingConfiguration
from omniagent.errors import ErrorCode, PlatformError
from omniagent.grounding_runtime import RetrievalHitProvider
from omniagent.identity import DevUserContext
from omniagent.postgres_repositories import SqlAlchemyPromptVersionRepository
from omniagent.profiles import AgentProfile
from omniagent.redaction import contains_secret
from omniagent.retrieval import RetrievalHit, SourceLocator
from omniagent.session_store import SessionStore, digest
from omniagent.telemetry import span
from omniagent.tool_registry import ToolRegistry

CACHE_VERSION = "query-evidence-v2"
CANONICAL_VERSION = "canonical-ordered-nfc-v2"
RETRIEVER_VERSION = "hybrid-rrf-or-k5-c20-r60"
EMBEDDING_VERSION = "fake-sha256-v1-1024"


class SemanticCacheRow(Base):
    __tablename__ = "semantic_cache"
    cache_id: Mapped[str] = mapped_column(Text, primary_key=True)
    namespace: Mapped[str] = mapped_column(Text, index=True)
    signature: Mapped[str] = mapped_column(Text)
    schema_version: Mapped[int] = mapped_column(Integer)
    embedding: Mapped[list[float]] = mapped_column(Vector(128))
    hits: Mapped[list[dict[str, object]]] = mapped_column(JSONB)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


@lru_cache(maxsize=1)
def code_version() -> str:
    root = Path(__file__).parent
    checksum = hashlib.sha256()
    for path in sorted(root.glob("*.py")):
        checksum.update(path.name.encode())
        checksum.update(path.read_bytes().replace(b"\r\n", b"\n"))
    return os.environ.get("OMNIAGENT_GIT_REVISION", "local") + ":" + checksum.hexdigest()


def canonical_terms(query: str) -> tuple[str, ...]:
    """Keep ordered, case-sensitive tokens and punctuation; aliases match whole queries.

    NFC and spacing are formatting equivalences. The small explicit topic aliases
    never rewrite a phrase inside a larger question or discard its negation/roles.
    This is an exact normalized-query key, not a semantic-similarity classifier.
    """
    value = " ".join(unicodedata.normalize("NFC", query).split())
    aliases = {"annual leave": "年假", "leave allowance": "年假", "warranty": "保修"}
    value = aliases.get(value.casefold(), value)
    return tuple(re.findall(r"\w+|[^\w\s]", value))


def semantic_vector(terms: tuple[str, ...]) -> list[float]:
    values = [0.0] * 128
    for term in terms:
        raw = hashlib.sha256(term.encode()).digest()
        values[int.from_bytes(raw[:2]) % 128] += 1 if raw[2] % 2 else -1
    norm = math.sqrt(sum(value * value for value in values))
    return [value / (norm or 1) for value in values]


def manifest(
    store: SessionStore,
    profile: AgentProfile,
    actor: DevUserContext,
    registry: ToolRegistry,
    *,
    embedding_version: str | None = None,
) -> dict[str, object]:
    with store.factory() as db:
        prompt = SqlAlchemyPromptVersionRepository(db).get(profile.prompt_version_id)
        sources = list(
            db.execute(
                select(SourceRow.source_id, SourceRow.checksum)
                .where(SourceRow.knowledge_base_id.in_(profile.knowledge_base_ids))
                .order_by(SourceRow.source_id)
            )
        )
    return {
        "profile": profile.model_dump(mode="json"),
        "prompt": prompt.content_hash if prompt else "missing",
        "knowledge_bases": sorted(profile.knowledge_base_ids),
        "sources": [list(row) for row in sources],
        "model": profile.model,
        "fallback_model": os.environ.get("OMNIAGENT_FALLBACK_MODEL", "unconfigured"),
        "provider": profile.provider_id,
        "provider_thinking": os.environ.get("OMNIAGENT_PROVIDER_THINKING", "default"),
        "fallback_thinking": os.environ.get("OMNIAGENT_FALLBACK_THINKING", "default"),
        "embedding": embedding_version or EmbeddingConfiguration.from_environment().version,
        "retriever": RETRIEVER_VERSION,
        "tools": [
            item.model_dump(mode="json")
            for item in sorted(registry.definitions(), key=lambda item: item.name)
            if item.name in profile.tool_ids
        ],
        "permissions": {
            "actor_hash": digest(actor.user_id),
            "role": actor.role,
            "profiles": sorted(actor.profile_ids),
        },
        "git_and_code": code_version(),
        "cache": CACHE_VERSION,
        "canonical": CANONICAL_VERSION,
    }


class SemanticRetriever:
    def __init__(
        self,
        store: SessionStore,
        profile: AgentProfile,
        actor: DevUserContext,
        registry: ToolRegistry,
        inner: RetrievalHitProvider,
        *,
        enabled: bool = True,
        embedding_version: str | None = None,
        embedding_model: str | None = None,
    ) -> None:
        self.store = store
        self.profile = profile
        self.actor = actor
        self.registry = registry
        self.inner = inner
        self.enabled = enabled
        self.last_hit = False
        self.embedding_version = embedding_version
        self.embedding_model = embedding_model or EmbeddingConfiguration.from_environment().model

    def retrieve_hits(self, knowledge_base_ids: list[str], query: str) -> list[RetrievalHit]:
        profile = self.store.profile(self.profile.profile_id, self.actor)
        if profile.version != self.profile.version or sorted(knowledge_base_ids) != sorted(
            profile.knowledge_base_ids
        ):
            raise PlatformError(ErrorCode.PERMISSION)
        self.last_hit = False
        terms = canonical_terms(query)
        if not self.enabled or not terms:
            return self.inner.retrieve_hits(knowledge_base_ids, query)
        namespace = digest(
            manifest(
                self.store,
                profile,
                self.actor,
                self.registry,
                embedding_version=self.embedding_version,
            )
        )
        signature = digest(terms)
        vector = semantic_vector(terms)
        now = datetime.fromtimestamp(self.store.clock(), UTC)
        with span("cache", profile_id=profile.profile_id) as current:
            with self.store.factory() as db:
                row = db.scalar(
                    select(SemanticCacheRow)
                    .where(
                        SemanticCacheRow.namespace == namespace,
                        SemanticCacheRow.signature == signature,
                        SemanticCacheRow.expires_at > now,
                        SemanticCacheRow.embedding.cosine_distance(vector) <= 0.02,
                    )
                    .limit(1)
                )
                if row is not None and row.schema_version == 1:
                    try:
                        hits = TypeAdapter(list[RetrievalHit]).validate_python(row.hits)
                    except ValidationError:
                        hits = []
                    valid = list(
                        db.scalars(
                            select(ChunkRow).where(
                                ChunkRow.chunk_id.in_([hit.chunk_id for hit in hits]),
                                ChunkRow.knowledge_base_id.in_(knowledge_base_ids),
                            )
                        )
                    )
                    actual = {chunk.chunk_id: chunk for chunk in valid}
                    if hits and all(
                        hit.chunk_id in actual
                        and hit.knowledge_base_id == actual[hit.chunk_id].knowledge_base_id
                        and hit.source_id == actual[hit.chunk_id].source_id
                        and hit.content == actual[hit.chunk_id].content
                        and actual[hit.chunk_id].embedding_model == self.embedding_model
                        and hit.chunk_index == actual[hit.chunk_id].chunk_index
                        and hit.source_locator
                        == SourceLocator.model_validate(
                            ChunkMetadata.model_validate(
                                actual[hit.chunk_id].chunk_metadata
                            ).model_dump(
                                include={
                                    "source_name",
                                    "page_number",
                                    "section",
                                    "char_start",
                                    "char_end",
                                }
                            )
                        )
                        and not contains_secret(hit.content)
                        for hit in hits
                    ):
                        self.last_hit = True
                        current.set_attribute("cache_hit", True)
                        return hits
            current.set_attribute("cache_hit", False)
            hits = self.inner.retrieve_hits(knowledge_base_ids, query)
            if any(hit.knowledge_base_id not in knowledge_base_ids for hit in hits):
                raise PlatformError(ErrorCode.PERMISSION)
            if any(contains_secret(hit.content) for hit in hits):
                raise PlatformError(ErrorCode.BAD_RESPONSE, "Sensitive evidence was blocked")
            if hits:
                entry = {
                    "cache_id": digest([namespace, signature]),
                    "namespace": namespace,
                    "signature": signature,
                    "schema_version": 1,
                    "embedding": vector,
                    "hits": [hit.model_dump(mode="json") for hit in hits],
                    "expires_at": now + timedelta(minutes=5),
                }
                with self.store.factory.begin() as db:
                    db.execute(delete(SemanticCacheRow).where(SemanticCacheRow.expires_at <= now))
                    overflow = (
                        select(SemanticCacheRow.cache_id)
                        .where(SemanticCacheRow.namespace == namespace)
                        .order_by(SemanticCacheRow.expires_at.desc())
                        .offset(127)
                    )
                    db.execute(
                        delete(SemanticCacheRow).where(SemanticCacheRow.cache_id.in_(overflow))
                    )
                    db.execute(
                        insert(SemanticCacheRow)
                        .values(**entry)
                        .on_conflict_do_update(
                            index_elements=[SemanticCacheRow.cache_id], set_=entry
                        )
                    )
            return hits
