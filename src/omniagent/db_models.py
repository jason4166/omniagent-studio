from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from omniagent.embeddings import EMBEDDING_DIMENSION


class Base(DeclarativeBase):
    pass


class KnowledgeBaseRow(Base):
    __tablename__ = "knowledge_bases"

    knowledge_base_id: Mapped[str] = mapped_column(Text, primary_key=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class SourceRow(Base):
    __tablename__ = "sources"

    __table_args__ = (
        CheckConstraint(
            "checksum ~ '^[0-9a-f]{64}$'",
            name="ck_sources_checksum_sha256",
        ),
        UniqueConstraint(
            "source_id",
            "knowledge_base_id",
            name="uq_sources_id_knowledge_base",
        ),
    )

    source_id: Mapped[str] = mapped_column(Text, primary_key=True)
    knowledge_base_id: Mapped[str] = mapped_column(
        ForeignKey("knowledge_bases.knowledge_base_id", ondelete="CASCADE"),
        nullable=False,
    )
    source_name: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    mime_type: Mapped[str] = mapped_column(Text, nullable=False)
    checksum: Mapped[str] = mapped_column(String(64), nullable=False)
    parser_version: Mapped[str] = mapped_column(Text, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    units: Mapped[list[dict[str, object]]] = mapped_column(JSONB, nullable=False)
    raw_bytes: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ChunkRow(Base):
    __tablename__ = "chunks"
    __table_args__ = (
        CheckConstraint(
            "chunk_index >= 0",
            name="ck_chunks_index_non_negative",
        ),
        ForeignKeyConstraint(
            ["source_id", "knowledge_base_id"],
            ["sources.source_id", "sources.knowledge_base_id"],
            name="fk_chunks_source_namespace",
            ondelete="CASCADE",
        ),
        UniqueConstraint(
            "source_id",
            "chunk_index",
            name="uq_chunks_source_index",
        ),
        Index(
            "ix_chunks_knowledge_base_id",
            "knowledge_base_id",
        ),
    )

    chunk_id: Mapped[str] = mapped_column(Text, primary_key=True)
    source_id: Mapped[str] = mapped_column(Text, nullable=False)
    knowledge_base_id: Mapped[str] = mapped_column(Text, nullable=False)
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    chunk_metadata: Mapped[dict[str, object]] = mapped_column(
        "metadata",
        JSONB,
        nullable=False,
    )
    embedding_model: Mapped[str] = mapped_column(Text, nullable=False)
    embedding: Mapped[list[float]] = mapped_column(
        Vector(EMBEDDING_DIMENSION),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class PromptVersionRow(Base):
    __tablename__ = "prompt_versions"

    prompt_version_id: Mapped[str] = mapped_column(Text, primary_key=True)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    variables: Mapped[list[str]] = mapped_column(
        ARRAY(Text),
        nullable=False,
        default=list,
        server_default=text("'{}'::text[]"),
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ToolDefinitionRow(Base):
    __tablename__ = "tool_definitions"
    __table_args__ = (
        CheckConstraint(
            "risk IN ('low', 'medium', 'high')",
            name="ck_tool_definitions_risk",
        ),
        CheckConstraint(
            "risk <> 'high' OR requires_approval",
            name="ck_tool_definitions_high_risk_approval",
        ),
    )

    tool_id: Mapped[str] = mapped_column(Text, primary_key=True)
    risk: Mapped[str] = mapped_column(Text, nullable=False)
    parameters_schema: Mapped[dict[str, object]] = mapped_column(
        JSONB,
        nullable=False,
    )
    allowed_roles: Mapped[list[str]] = mapped_column(
        ARRAY(Text),
        nullable=False,
        default=list,
        server_default=text("'{}'::text[]"),
    )
    tags: Mapped[list[str]] = mapped_column(
        ARRAY(Text),
        nullable=False,
        default=list,
        server_default=text("'{}'::text[]"),
    )
    requires_approval: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default=text("true"),
    )


class AgentProfileRow(Base):
    __tablename__ = "agent_profiles"
    __table_args__ = (CheckConstraint("version >= 1", name="ck_agent_profiles_version_positive"),)

    profile_id: Mapped[str] = mapped_column(Text, primary_key=True)
    version: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=1,
        server_default=text("1"),
    )
    enabled: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default=text("true"),
    )
    prompt_version_id: Mapped[str] = mapped_column(
        ForeignKey("prompt_versions.prompt_version_id", ondelete="RESTRICT"),
        nullable=False,
    )
    budget_policy_id: Mapped[str] = mapped_column(Text, nullable=False)
    approval_policy_id: Mapped[str] = mapped_column(Text, nullable=False)


class AgentProfileKnowledgeBaseRow(Base):
    __tablename__ = "agent_profile_knowledge_bases"

    profile_id: Mapped[str] = mapped_column(
        ForeignKey("agent_profiles.profile_id", ondelete="CASCADE"),
        primary_key=True,
    )
    knowledge_base_id: Mapped[str] = mapped_column(
        ForeignKey("knowledge_bases.knowledge_base_id", ondelete="RESTRICT"),
        primary_key=True,
    )


class AgentProfileToolRow(Base):
    __tablename__ = "agent_profile_tools"

    profile_id: Mapped[str] = mapped_column(
        ForeignKey("agent_profiles.profile_id", ondelete="CASCADE"),
        primary_key=True,
    )
    tool_id: Mapped[str] = mapped_column(
        ForeignKey("tool_definitions.tool_id", ondelete="RESTRICT"),
        primary_key=True,
    )