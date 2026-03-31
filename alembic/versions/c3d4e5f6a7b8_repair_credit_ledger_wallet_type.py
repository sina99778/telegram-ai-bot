"""repair credit ledger wallet_type drift

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-03-31
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "c3d4e5f6a7b8"
down_revision = "b2c3d4e5f6a7"
branch_labels = None
depends_on = None


wallet_enum = sa.Enum("NORMAL", "VIP", name="wallettype")


def _get_column_info(table_name: str, column_name: str) -> dict | None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    for column in inspector.get_columns(table_name):
        if column["name"] == column_name:
            return column
    return None


def upgrade() -> None:
    bind = op.get_bind()
    wallet_enum.create(bind, checkfirst=True)

    wallet_column = _get_column_info("credit_ledger", "wallet_type")
    if wallet_column is None:
        op.add_column(
            "credit_ledger",
            sa.Column("wallet_type", sa.String(length=20), nullable=True, server_default="NORMAL"),
        )

    op.execute("UPDATE credit_ledger SET wallet_type = 'NORMAL' WHERE wallet_type IS NULL")

    if bind.dialect.name == "postgresql":
        wallet_column = _get_column_info("credit_ledger", "wallet_type")
        if wallet_column is not None and not isinstance(wallet_column["type"], sa.Enum):
            op.alter_column(
                "credit_ledger",
                "wallet_type",
                existing_type=wallet_column["type"],
                type_=wallet_enum,
                postgresql_using="wallet_type::wallettype",
            )

    wallet_column = _get_column_info("credit_ledger", "wallet_type")
    if wallet_column is not None and wallet_column.get("nullable", True):
        existing_type = wallet_column["type"] if wallet_column is not None else sa.String(length=20)
        op.alter_column(
            "credit_ledger",
            "wallet_type",
            existing_type=existing_type,
            nullable=False,
            server_default="NORMAL",
        )


def downgrade() -> None:
    wallet_column = _get_column_info("credit_ledger", "wallet_type")
    if wallet_column is not None:
        op.drop_column("credit_ledger", "wallet_type")
