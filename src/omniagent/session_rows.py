"""Persistence tables for sessions, approvals, event replay and mock effects."""

from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from omniagent.db_models import Base


class SessionRow(Base):
    __tablename__ = "sessions"
    thread_id: Mapped[str] = mapped_column(Text, primary_key=True)
    user_id: Mapped[str] = mapped_column(Text, index=True)
    profile_id: Mapped[str] = mapped_column(
        ForeignKey("agent_profiles.profile_id", ondelete="RESTRICT")
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    data: Mapped[dict[str, object]] = mapped_column(JSONB)
    sequence: Mapped[int] = mapped_column(Integer, default=0)


class ApprovalRow(Base):
    __tablename__ = "approvals"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending','approved','rejected','expired','executed','failed')",
            name="ck_approval_status",
        ),
    )
    approval_id: Mapped[str] = mapped_column(Text, primary_key=True)
    thread_id: Mapped[str] = mapped_column(
        ForeignKey("sessions.thread_id", ondelete="CASCADE"), index=True
    )
    run_id: Mapped[str] = mapped_column(Text, unique=True)
    user_id: Mapped[str] = mapped_column(Text)
    profile_id: Mapped[str] = mapped_column(Text)
    profile_version: Mapped[int] = mapped_column(Integer)
    tool_name: Mapped[str] = mapped_column(Text)
    policy_hash: Mapped[str] = mapped_column(Text)
    arguments: Mapped[dict[str, object]] = mapped_column(JSONB)
    risk: Mapped[str] = mapped_column(Text)
    reason: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, default="pending")
    version: Mapped[int] = mapped_column(Integer, default=1)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    idempotency_key: Mapped[str] = mapped_column(Text, unique=True)
    decision_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    decision_hash: Mapped[str | None] = mapped_column(Text, nullable=True)
    decision_by: Mapped[str | None] = mapped_column(Text, nullable=True)
    decision_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    result: Mapped[dict[str, object] | None] = mapped_column(JSONB, nullable=True)


class EventRow(Base):
    __tablename__ = "session_events"
    __table_args__ = (UniqueConstraint("thread_id", "sequence", name="uq_thread_event_sequence"),)
    event_id: Mapped[str] = mapped_column(Text, primary_key=True)
    thread_id: Mapped[str] = mapped_column(
        ForeignKey("sessions.thread_id", ondelete="CASCADE"), index=True
    )
    run_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    sequence: Mapped[int] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(Text)
    data: Mapped[dict[str, object]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class RequestRow(Base):
    __tablename__ = "session_requests"
    thread_id: Mapped[str] = mapped_column(
        ForeignKey("sessions.thread_id", ondelete="CASCADE"), primary_key=True
    )
    request_key: Mapped[str] = mapped_column(Text, primary_key=True)
    payload_hash: Mapped[str] = mapped_column(Text)
    run_id: Mapped[str] = mapped_column(Text)
    response: Mapped[dict[str, object] | None] = mapped_column(JSONB, nullable=True)


class EffectRow(Base):
    __tablename__ = "mock_effects"
    idempotency_key: Mapped[str] = mapped_column(Text, primary_key=True)
    payload_hash: Mapped[str] = mapped_column(Text)
    tool_name: Mapped[str] = mapped_column(Text)
    result: Mapped[dict[str, object]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class AuditRow(Base):
    __tablename__ = "audit_events"
    audit_id: Mapped[str] = mapped_column(Text, primary_key=True)
    actor_hash: Mapped[str] = mapped_column(Text)
    thread_id: Mapped[str] = mapped_column(Text, index=True)
    run_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    action: Mapped[str] = mapped_column(Text)
    details: Mapped[dict[str, object]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
