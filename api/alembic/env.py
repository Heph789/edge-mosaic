"""Alembic environment — wired to the app's models and DATABASE_URL."""

from __future__ import annotations

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from app.config import DATABASE_URL
from app.models import Base

config = context.config
config.set_main_option("sqlalchemy.url", DATABASE_URL)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata

# Shared by every deployer that runs `alembic upgrade head`. The api service and both cron
# services (scrape, digest) run it in Railway's pre-deploy step, and a push redeploys them
# concurrently — so they'd otherwise race to apply a brand-new migration at the same time.
_MIGRATION_LOCK_KEY = 0x6D6F73616963  # "mosaic"


def run_migrations_offline() -> None:
    context.configure(
        url=DATABASE_URL,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        if connection.dialect.name == "postgresql":
            # Serialize concurrent `alembic upgrade head` across services: the loser blocks
            # here until the winner commits, then finds the schema already at head and no-ops.
            # Session-level lock — released when this connection disconnects even if a migration
            # raises; NullPool guarantees that disconnect. commit() ends the implicit txn the
            # lock query opened so Alembic can manage its own transaction (the lock outlives it).
            connection.exec_driver_sql(f"SELECT pg_advisory_lock({_MIGRATION_LOCK_KEY})")
            connection.commit()
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            render_as_batch=True,  # SQLite-friendly ALTERs; harmless on Postgres
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
