"""Persist per-attempt model token reservations for idempotent settlement."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "b620d784ef32"
down_revision = "f2176a0983ab"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "model_quota_reservations",
        sa.Column("reservation_id", sa.Text(), primary_key=True),
        sa.Column("actor_hash", sa.Text(), nullable=False),
        sa.Column("token_windows", JSONB(), nullable=False),
        sa.Column("reserved_tokens", sa.Integer(), nullable=False),
        sa.Column("actual_tokens", sa.Integer(), nullable=True),
        sa.Column("limit_exceeded", sa.Boolean(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("reserved_tokens > 0", name="ck_model_quota_reserved_positive"),
        sa.CheckConstraint(
            "actual_tokens IS NULL OR actual_tokens >= 0", name="ck_model_quota_actual_nonnegative"
        ),
    )
    op.create_index(
        "ix_model_quota_reservations_expires_at", "model_quota_reservations", ["expires_at"]
    )
    op.execute(
        "DO $$ BEGIN IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'omniagent_runtime') "
        "THEN GRANT SELECT, INSERT, UPDATE, DELETE ON model_quota_reservations "
        "TO omniagent_runtime; END IF; END $$"
    )


def downgrade() -> None:
    op.drop_table("model_quota_reservations")
