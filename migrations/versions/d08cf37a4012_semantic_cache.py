"""Versioned, permission-partitioned semantic evidence cache.
Revision ID: d08cf37a4012
Revises: 91c0d7e2f301
"""

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects.postgresql import JSONB

revision = "d08cf37a4012"
down_revision = "91c0d7e2f301"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "semantic_cache",
        sa.Column("cache_id", sa.Text(), primary_key=True),
        sa.Column("namespace", sa.Text(), nullable=False),
        sa.Column("signature", sa.Text(), nullable=False),
        sa.Column("schema_version", sa.Integer(), nullable=False),
        sa.Column("embedding", Vector(128), nullable=False),
        sa.Column("hits", JSONB(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_semantic_cache_namespace", "semantic_cache", ["namespace"])
    op.create_index("ix_semantic_cache_expires_at", "semantic_cache", ["expires_at"])


def downgrade() -> None:
    op.drop_table("semantic_cache")
