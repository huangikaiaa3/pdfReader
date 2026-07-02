"""add document profiles

Revision ID: f2c4d6e8a9b1
Revises: e7b1c2d3f4a5
Create Date: 2026-07-02
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "f2c4d6e8a9b1"
down_revision = "e7b1c2d3f4a5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "document_profiles",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("document_version_id", sa.Uuid(), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("document_type", sa.String(length=255), nullable=False),
        sa.Column("primary_subject", sa.String(length=255), nullable=True),
        sa.Column("key_dates_json", sa.JSON(), nullable=False),
        sa.Column("key_addresses_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["document_version_id"], ["document_versions.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("document_version_id"),
    )
    op.create_index(op.f("ix_document_profiles_document_version_id"), "document_profiles", ["document_version_id"], unique=True)


def downgrade() -> None:
    op.drop_index(op.f("ix_document_profiles_document_version_id"), table_name="document_profiles")
    op.drop_table("document_profiles")
