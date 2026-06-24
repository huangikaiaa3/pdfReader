"""add pipeline chunks and embeddings

Revision ID: f89cded8a01a
Revises: d8f40dd46876
Create Date: 2026-06-24 15:13:27.272563

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f89cded8a01a'
down_revision: Union[str, Sequence[str], None] = 'd8f40dd46876'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('document_chunks',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('document_version_id', sa.Uuid(), nullable=False),
    sa.Column('chunk_index', sa.Integer(), nullable=False),
    sa.Column('start_page_number', sa.Integer(), nullable=False),
    sa.Column('end_page_number', sa.Integer(), nullable=False),
    sa.Column('text', sa.Text(), nullable=False),
    sa.Column('char_count', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['document_version_id'], ['document_versions.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('document_version_id', 'chunk_index', name='uq_document_chunks_version_index')
    )
    op.create_index(op.f('ix_document_chunks_document_version_id'), 'document_chunks', ['document_version_id'], unique=False)
    op.create_table('chunk_embeddings',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('document_chunk_id', sa.Uuid(), nullable=False),
    sa.Column('embedding_model', sa.String(length=255), nullable=False),
    sa.Column('dimensions', sa.Integer(), nullable=False),
    sa.Column('vector', sa.Text(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['document_chunk_id'], ['document_chunks.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('document_chunk_id', 'embedding_model', name='uq_chunk_embeddings_chunk_model')
    )
    op.create_index(op.f('ix_chunk_embeddings_document_chunk_id'), 'chunk_embeddings', ['document_chunk_id'], unique=False)
    op.alter_column('document_versions', 'extraction_status', new_column_name='pipeline_status')


def downgrade() -> None:
    """Downgrade schema."""
    op.alter_column('document_versions', 'pipeline_status', new_column_name='extraction_status')
    op.drop_index(op.f('ix_chunk_embeddings_document_chunk_id'), table_name='chunk_embeddings')
    op.drop_table('chunk_embeddings')
    op.drop_index(op.f('ix_document_chunks_document_version_id'), table_name='document_chunks')
    op.drop_table('document_chunks')
