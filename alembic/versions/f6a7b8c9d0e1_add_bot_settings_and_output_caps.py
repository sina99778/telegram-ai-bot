"""add bot_settings table and backfill text output-token caps

Revision ID: f6a7b8c9d0e1
Revises: d4e5f6a7b8c9
Create Date: 2026-06-01
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "f6a7b8c9d0e1"
down_revision = "d4e5f6a7b8c9"
branch_labels = None
depends_on = None


def _has_table(table_name: str) -> bool:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return table_name in inspector.get_table_names()


def upgrade() -> None:
    # ── Runtime-editable key/value config ──
    if not _has_table("bot_settings"):
        op.create_table(
            "bot_settings",
            sa.Column("key", sa.String(length=64), primary_key=True),
            sa.Column("value", sa.String(length=255), nullable=False),
            sa.Column("updated_by", sa.BigInteger(), nullable=True),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        )

    # ── Backfill output-token caps on text features that have none ──
    # Output tokens are the expensive half of a request; cap verbose answers.
    op.execute(
        "UPDATE feature_configs SET max_output_tokens = 800 "
        "WHERE name = 'FLASH_TEXT' AND max_output_tokens IS NULL"
    )
    op.execute(
        "UPDATE feature_configs SET max_output_tokens = 1500 "
        "WHERE name = 'PRO_TEXT' AND max_output_tokens IS NULL"
    )


def downgrade() -> None:
    # Leave max_output_tokens backfill in place (harmless); only drop the table.
    if _has_table("bot_settings"):
        op.drop_table("bot_settings")
