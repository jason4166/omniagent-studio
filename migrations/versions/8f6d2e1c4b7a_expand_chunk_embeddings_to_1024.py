"""expand chunk embeddings to 1024 dimensions

Revision ID: 8f6d2e1c4b7a
Revises: 1dbcd1fcc22d
Create Date: 2026-09-07 19:05:00.000000

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "8f6d2e1c4b7a"
down_revision: str | Sequence[str] | None = "1dbcd1fcc22d"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Pad existing 8-dimensional vectors without changing cosine direction."""
    op.execute(
        """
        ALTER TABLE chunks
        ALTER COLUMN embedding TYPE vector(1024)
        USING array_to_vector(
            vector_to_float4(embedding, 8, false)
            || array_fill(0::real, ARRAY[1016]),
            1024,
            false
        )
        """
    )


def downgrade() -> None:
    """Restore the original eight signal dimensions."""
    op.execute(
        """
        ALTER TABLE chunks
        ALTER COLUMN embedding TYPE vector(8)
        USING subvector(embedding, 1, 8)::vector(8)
        """
    )
