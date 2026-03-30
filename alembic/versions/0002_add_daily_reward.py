"""add last_daily_reward to users

Revision ID: 0002_add_daily_reward
Create Date: 2026-03-30
"""
from alembic import op
import sqlalchemy as sa

revision = '0002_add_daily_reward'
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add last_daily_reward column — nullable so existing rows are unaffected
    op.add_column('users', sa.Column('last_daily_reward', sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column('users', 'last_daily_reward')
