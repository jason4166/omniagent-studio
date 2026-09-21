"""Durable identities, revocable login sessions and cross-worker quota reservations."""

from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Integer, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from omniagent.db_models import Base


class AccountRow(Base):
    __tablename__ = "accounts"
    user_id: Mapped[str] = mapped_column(Text, primary_key=True)
    username: Mapped[str] = mapped_column(Text, unique=True)
    password_hash: Mapped[str] = mapped_column(Text)
    role: Mapped[str] = mapped_column(Text)
    profile_ids: Mapped[list[str]] = mapped_column(JSONB)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )


class LoginRow(Base):
    __tablename__ = "login_sessions"
    token_hash: Mapped[str] = mapped_column(Text, primary_key=True)
    user_id: Mapped[str] = mapped_column(
        ForeignKey("accounts.user_id", ondelete="CASCADE"), index=True
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class QuotaRow(Base):
    __tablename__ = "quota_windows"
    key: Mapped[str] = mapped_column(Text, primary_key=True)
    used: Mapped[int] = mapped_column(Integer)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class ModelQuotaReservationRow(Base):
    __tablename__ = "model_quota_reservations"
    __table_args__ = (
        CheckConstraint("reserved_tokens > 0", name="ck_model_quota_reserved_positive"),
        CheckConstraint(
            "actual_tokens IS NULL OR actual_tokens >= 0", name="ck_model_quota_actual_nonnegative"
        ),
    )
    reservation_id: Mapped[str] = mapped_column(Text, primary_key=True)
    actor_hash: Mapped[str] = mapped_column(Text)
    token_windows: Mapped[dict[str, int]] = mapped_column(JSONB)
    reserved_tokens: Mapped[int] = mapped_column(Integer)
    actual_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    limit_exceeded: Mapped[bool] = mapped_column(Boolean, default=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class StreamLeaseRow(Base):
    __tablename__ = "stream_leases"
    lease_id: Mapped[str] = mapped_column(Text, primary_key=True)
    user_id: Mapped[str] = mapped_column(Text, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
