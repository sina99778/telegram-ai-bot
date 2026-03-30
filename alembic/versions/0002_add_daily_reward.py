"""add last_daily_reward to users

Revision ID: a1b2c3d4e5f6
Revises:
Create Date: 2026-03-30
"""
from alembic import op
import sqlalchemy as sa

revision = 'a1b2c3d4e5f6'
down_revision = None   # root — this DB was bootstrapped with create_all, not Alembic
branch_labels = None
depends_on = None


def upgrade() -> None:
    # IF NOT EXISTS makes this idempotent — safe to run even if column already exists
    op.execute(
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS "
        "last_daily_reward TIMESTAMPTZ"
    )


def downgrade() -> None:
    op.drop_column('users', 'last_daily_reward')
