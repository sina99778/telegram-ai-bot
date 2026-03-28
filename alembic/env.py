"""
alembic/env.py
~~~~~~~~~~~~~~
Async Alembic environment for SQLAlchemy 2.0 + asyncpg.

The database URL is loaded at runtime from ``app.core.config.settings``
so that credentials are never hardcoded in configuration files.
"""

from __future__ import annotations

import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from app.core.config import settings

# ── Import all models so Base.metadata contains every table ──
from app.db.models import Base  # noqa: F401  (side-effect import)

# ── Alembic Config object ────────────────────
config = context.config

# Interpret the alembic.ini logging config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# MetaData target for 'autogenerate' support
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    This configures the context with just a URL and not an Engine,
    though an Engine is acceptable here as well.  By skipping the
    Engine creation we don't even need a DBAPI to be available.

    Calls to ``context.execute()`` emit the given string to the
    script output.
    """
    context.configure(
        url=settings.database_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    """Shared helper — configures the migration context with a live
    connection and runs all pending migrations."""
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
    )

    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """Create an async engine and run migrations inside its connection."""
    configuration = config.get_section(config.config_ini_section, {})
    configuration["sqlalchemy.url"] = settings.database_url

    connectable = async_engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode.

    In this scenario we create an async engine and associate a
    connection with the context.
    """
    asyncio.run(run_async_migrations())


# ── Determine which mode to run ──────────────
if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
