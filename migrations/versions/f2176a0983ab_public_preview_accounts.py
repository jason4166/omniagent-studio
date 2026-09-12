"""Add bounded, independently identified public reviewer accounts."""

import sqlalchemy as sa
from alembic import op

revision = "f2176a0983ab"
down_revision = "e91b0c27a501"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("accounts", sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index("ix_accounts_expires_at", "accounts", ["expires_at"])


def downgrade() -> None:
    op.execute("UPDATE accounts SET enabled = false WHERE expires_at IS NOT NULL")
    op.drop_index("ix_accounts_expires_at", table_name="accounts")
    op.drop_column("accounts", "expires_at")
