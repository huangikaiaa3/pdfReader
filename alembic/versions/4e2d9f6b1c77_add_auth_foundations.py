"""add auth foundations

Revision ID: 4e2d9f6b1c77
Revises: c3a7e1b2d4f5
Create Date: 2026-06-29 00:00:00.000000

"""

from typing import Sequence, Union
import uuid

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "4e2d9f6b1c77"
down_revision: Union[str, None] = "c3a7e1b2d4f5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("display_name", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_users_email"), "users", ["email"], unique=True)

    op.create_table(
        "api_keys",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("key_prefix", sa.String(length=32), nullable=False),
        sa.Column("key_hash", sa.String(length=64), nullable=False),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("key_hash"),
    )
    op.create_index(op.f("ix_api_keys_key_hash"), "api_keys", ["key_hash"], unique=True)
    op.create_index(op.f("ix_api_keys_key_prefix"), "api_keys", ["key_prefix"], unique=False)
    op.create_index(op.f("ix_api_keys_user_id"), "api_keys", ["user_id"], unique=False)

    op.add_column("documents", sa.Column("owner_user_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.create_index(op.f("ix_documents_owner_user_id"), "documents", ["owner_user_id"], unique=False)
    op.create_foreign_key(
        "documents_owner_user_id_fkey",
        "documents",
        "users",
        ["owner_user_id"],
        ["id"],
    )

    legacy_user_id = uuid.uuid4()
    op.execute(
        sa.text(
            """
            INSERT INTO users (id, email, display_name)
            VALUES (:id, :email, :display_name)
            """
        ).bindparams(
            id=legacy_user_id,
            email="legacy-local-user@pdfreader.local",
            display_name="Legacy Local User",
        )
    )
    op.execute(
        sa.text(
            """
            UPDATE documents
            SET owner_user_id = :legacy_user_id
            WHERE owner_user_id IS NULL
            """
        ).bindparams(legacy_user_id=legacy_user_id)
    )
    op.alter_column("documents", "owner_user_id", nullable=False)


def downgrade() -> None:
    op.drop_constraint("documents_owner_user_id_fkey", "documents", type_="foreignkey")
    op.drop_index(op.f("ix_documents_owner_user_id"), table_name="documents")
    op.drop_column("documents", "owner_user_id")

    op.drop_index(op.f("ix_api_keys_user_id"), table_name="api_keys")
    op.drop_index(op.f("ix_api_keys_key_prefix"), table_name="api_keys")
    op.drop_index(op.f("ix_api_keys_key_hash"), table_name="api_keys")
    op.drop_table("api_keys")

    op.drop_index(op.f("ix_users_email"), table_name="users")
    op.drop_table("users")
