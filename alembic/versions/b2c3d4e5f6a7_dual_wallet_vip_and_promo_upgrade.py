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


def _reconcile_pg_enum(conn, type_name: str, expected_values: list[str]) -> None:
    """Make sure a PostgreSQL enum type carries every expected value.

    This guards against the common situation where ``Base.metadata.create_all``
    created the type with a different value set (for example the SQLAlchemy
    default, which uses the Python ``Enum`` member *names* — ``GIFT_…`` —
    rather than the ``.value`` strings — ``gift_…``). In that state a later
    ``Enum.create(checkfirst=True)`` here is a no-op (the *name* exists), and
    the subsequent ``ADD COLUMN … DEFAULT 'gift_normal_credits'`` then bombs
    with ``invalid input value for enum``.

    Behaviour:
      * Non-PostgreSQL backend → no-op.
      * Type doesn't exist → no-op (caller's ``.create()`` will create it).
      * All expected values already present → no-op.
      * Some expected values missing AND no column uses the type yet →
        drop the type so caller's ``.create()`` recreates it cleanly.
      * Some expected values missing AND a column already uses the type →
        ``ALTER TYPE … ADD VALUE IF NOT EXISTS`` for each missing label.
    """
    if conn.dialect.name != "postgresql":
        return

    type_exists = conn.execute(
        sa.text("SELECT 1 FROM pg_type WHERE typname = :n"),
        {"n": type_name},
    ).scalar()
    if not type_exists:
        return

    existing_rows = conn.execute(
        sa.text(
            "SELECT e.enumlabel "
            "FROM pg_type t JOIN pg_enum e ON t.oid = e.enumtypid "
            "WHERE t.typname = :n"
        ),
        {"n": type_name},
    ).all()
    existing = {row[0] for row in existing_rows}
    missing = [v for v in expected_values if v not in existing]
    if not missing:
        return

    in_use = conn.execute(
        sa.text(
            "SELECT 1 FROM pg_attribute a "
            "JOIN pg_type t ON a.atttypid = t.oid "
            "WHERE t.typname = :n AND NOT a.attisdropped LIMIT 1"
        ),
        {"n": type_name},
    ).scalar()

    if in_use:
        # PG 12+ allows ADD VALUE inside a transaction as long as the type
        # itself wasn't created in this same transaction (it wasn't — we
        # just confirmed it pre-exists).
        for value in missing:
            op.execute(sa.text(f"ALTER TYPE {type_name} ADD VALUE IF NOT EXISTS '{value}'"))
    else:
        op.execute(sa.text(f"DROP TYPE {type_name}"))


def upgrade() -> None:
    bind = op.get_bind()

    # Reconcile any pre-existing enum types whose value set drifted from what
    # this migration expects (typical when create_all bootstrapped the schema
    # with SQLAlchemy's default uppercase labels).
    _reconcile_pg_enum(bind, "wallettype", ["NORMAL", "VIP"])
    _reconcile_pg_enum(
        bind,
        "promocodekind",
        ["gift_normal_credits", "gift_vip_credits", "gift_vip_days", "discount_percent"],
    )

    wallet_enum.create(bind, checkfirst=True)
    promo_kind_enum.create(bind, checkfirst=True)

    if not _has_column("users", "vip_credits"):
        op.add_column("users", sa.Column("vip_credits", sa.Integer(), nullable=False, server_default="0"))
    if _has_column("users", "premium_credits"):
        op.execute(
            "UPDATE users "
            "SET vip_credits = COALESCE(premium_credits, 0) "
            "WHERE premium_credits IS NOT NULL"
        )
        op.drop_column("users", "premium_credits")

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
        op.add_column("users", sa.Column("premium_credits", sa.Integer(), nullable=False, server_default="0"))
        op.execute(
            "UPDATE users "
            "SET premium_credits = COALESCE(vip_credits, 0) "
            "WHERE vip_credits IS NOT NULL"
        )
        op.drop_column("users", "vip_credits")

    bind = op.get_bind()
    promo_kind_enum.drop(bind, checkfirst=True)
    wallet_enum.drop(bind, checkfirst=True)
