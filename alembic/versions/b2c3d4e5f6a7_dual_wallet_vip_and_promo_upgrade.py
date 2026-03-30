"""dual wallet vip and promo upgrade

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-03-31
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "b2c3d4e5f6a7"
down_revision = "a1b2c3d4e5f6"
branch_labels = None
depends_on = None


wallet_enum = sa.Enum("NORMAL", "VIP", name="wallettype")
promo_kind_enum = sa.Enum(
    "gift_normal_credits",
    "gift_vip_credits",
    "gift_vip_days",
    "discount_percent",
    name="promocodekind",
)


def _has_column(table_name: str, column_name: str) -> bool:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return column_name in {column["name"] for column in inspector.get_columns(table_name)}


def upgrade() -> None:
    bind = op.get_bind()
    wallet_enum.create(bind, checkfirst=True)
    promo_kind_enum.create(bind, checkfirst=True)

    if _has_column("users", "premium_credits") and not _has_column("users", "vip_credits"):
        op.alter_column("users", "premium_credits", new_column_name="vip_credits")
    elif not _has_column("users", "vip_credits"):
        op.add_column("users", sa.Column("vip_credits", sa.Integer(), nullable=False, server_default="0"))

    if not _has_column("credit_ledger", "wallet_type"):
        op.add_column(
            "credit_ledger",
            sa.Column("wallet_type", wallet_enum, nullable=False, server_default="NORMAL"),
        )

    if not _has_column("promo_codes", "kind"):
        op.add_column(
            "promo_codes",
            sa.Column("kind", promo_kind_enum, nullable=False, server_default="gift_normal_credits"),
        )
    if _has_column("promo_codes", "credits") and not _has_column("promo_codes", "normal_credits"):
        op.alter_column("promo_codes", "credits", new_column_name="normal_credits")
    elif not _has_column("promo_codes", "normal_credits"):
        op.add_column("promo_codes", sa.Column("normal_credits", sa.Integer(), nullable=False, server_default="0"))

    for column_name, default_value in (
        ("vip_credits", "0"),
        ("discount_percent", "0"),
        ("max_uses", "1"),
        ("used_count", "0"),
        ("max_uses_per_user", "1"),
    ):
        if not _has_column("promo_codes", column_name):
            op.add_column(
                "promo_codes",
                sa.Column(column_name, sa.Integer(), nullable=False, server_default=default_value),
            )

    if not _has_column("promo_codes", "is_active"):
        op.add_column(
            "promo_codes",
            sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        )
    if not _has_column("promo_codes", "created_by_admin_id"):
        op.add_column("promo_codes", sa.Column("created_by_admin_id", sa.BigInteger(), nullable=True))

    if not _has_column("user_promos", "used_count"):
        op.add_column("user_promos", sa.Column("used_count", sa.Integer(), nullable=False, server_default="0"))

    op.execute("UPDATE users SET vip_credits = COALESCE(vip_credits, 0)")
    op.execute(
        "UPDATE credit_ledger SET wallet_type = 'VIP' "
        "WHERE reference_type IN ('payment_tx', 'nowpayments_ipn', 'image_generation')"
    )


def downgrade() -> None:
    if _has_column("user_promos", "used_count"):
        op.drop_column("user_promos", "used_count")

    for column_name in (
        "created_by_admin_id",
        "is_active",
        "max_uses_per_user",
        "used_count",
        "max_uses",
        "discount_percent",
        "vip_credits",
    ):
        if _has_column("promo_codes", column_name):
            op.drop_column("promo_codes", column_name)

    if _has_column("promo_codes", "kind"):
        op.drop_column("promo_codes", "kind")

    if _has_column("promo_codes", "normal_credits") and not _has_column("promo_codes", "credits"):
        op.alter_column("promo_codes", "normal_credits", new_column_name="credits")

    if _has_column("credit_ledger", "wallet_type"):
        op.drop_column("credit_ledger", "wallet_type")

    if _has_column("users", "vip_credits") and not _has_column("users", "premium_credits"):
        op.alter_column("users", "vip_credits", new_column_name="premium_credits")

    bind = op.get_bind()
    promo_kind_enum.drop(bind, checkfirst=True)
    wallet_enum.drop(bind, checkfirst=True)
