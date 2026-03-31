"""add feature usage tracking and image model defaults

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
Create Date: 2026-03-31
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "d4e5f6a7b8c9"
down_revision = "c3d4e5f6a7b8"
branch_labels = None
depends_on = None


def _has_table(table_name: str) -> bool:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return table_name in inspector.get_table_names()


def upgrade() -> None:
    if not _has_table("feature_usage"):
        op.create_table(
            "feature_usage",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("scope_type", sa.String(length=20), nullable=False),
            sa.Column("scope_id", sa.BigInteger(), nullable=False),
            sa.Column("feature", sa.String(length=50), nullable=False),
            sa.Column("used_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("reset_date", sa.Date(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.UniqueConstraint("scope_type", "scope_id", "feature", "reset_date", name="uq_feature_usage_scope_feature_reset"),
        )
        op.create_index("ix_feature_usage_scope_feature", "feature_usage", ["scope_type", "scope_id", "feature"])

    op.execute(
        "UPDATE feature_configs "
        "SET model_name = 'gemini-3.1-flash-image-preview' "
        "WHERE name = 'IMAGE_GEN' "
        "AND (model_name IS NULL OR model_name = '' OR model_name = 'gemini-3-pro-image-preview')"
    )
    op.execute(
        "UPDATE feature_configs "
        "SET model_name = 'gemini-3.1-flash-lite-preview' "
        "WHERE name = 'FLASH_TEXT' AND (model_name IS NULL OR model_name = '')"
    )
    op.execute(
        "UPDATE feature_configs "
        "SET model_name = 'gemini-3.1-pro-preview' "
        "WHERE name = 'PRO_TEXT' AND (model_name IS NULL OR model_name = '')"
    )


def downgrade() -> None:
    if _has_table("feature_usage"):
        op.drop_index("ix_feature_usage_scope_feature", table_name="feature_usage")
        op.drop_table("feature_usage")
