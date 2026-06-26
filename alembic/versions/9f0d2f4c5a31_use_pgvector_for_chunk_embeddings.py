"""use pgvector for chunk embeddings

Revision ID: 9f0d2f4c5a31
Revises: f89cded8a01a
Create Date: 2026-06-26 17:20:00.000000

"""

from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "9f0d2f4c5a31"
down_revision: Union[str, Sequence[str], None] = "f89cded8a01a"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""

    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.execute(
        """
        ALTER TABLE chunk_embeddings
        ALTER COLUMN vector TYPE vector(768)
        USING vector::vector(768)
        """
    )


def downgrade() -> None:
    """Downgrade schema."""

    op.execute(
        """
        ALTER TABLE chunk_embeddings
        ALTER COLUMN vector TYPE text
        USING vector::text
        """
    )
