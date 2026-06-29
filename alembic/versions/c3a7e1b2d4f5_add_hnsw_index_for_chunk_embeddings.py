"""add hnsw index for chunk embeddings

Revision ID: c3a7e1b2d4f5
Revises: 9f0d2f4c5a31
Create Date: 2026-06-29 00:00:00.000000

"""

from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "c3a7e1b2d4f5"
down_revision: Union[str, None] = "9f0d2f4c5a31"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_chunk_embeddings_vector_hnsw
        ON chunk_embeddings
        USING hnsw (vector vector_cosine_ops)
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_chunk_embeddings_vector_hnsw")
