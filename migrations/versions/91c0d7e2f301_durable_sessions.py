"""Durable sessions, approvals and idempotency.
Revision ID: 91c0d7e2f301
Revises: 8f6d2e1c4b7a
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

from omniagent.session_rows import (
    ApprovalRow,
    AuditRow,
    EffectRow,
    EventRow,
    RequestRow,
    SessionRow,
)

revision = "91c0d7e2f301"
down_revision = "8f6d2e1c4b7a"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "agent_profiles",
        sa.Column("settings", JSONB, server_default=sa.text("'{}'::jsonb"), nullable=False),
    )
    op.add_column(
        "tool_definitions",
        sa.Column("settings", JSONB, server_default=sa.text("'{}'::jsonb"), nullable=False),
    )
    for table in (
        SessionRow.__table__,
        ApprovalRow.__table__,
        EventRow.__table__,
        RequestRow.__table__,
        EffectRow.__table__,
        AuditRow.__table__,
    ):
        table.create(op.get_bind())


def downgrade() -> None:
    for name in (
        "audit_events",
        "mock_effects",
        "session_requests",
        "session_events",
        "approvals",
        "sessions",
    ):
        op.drop_table(name)
    op.drop_column("tool_definitions", "settings")
    op.drop_column("agent_profiles", "settings")
