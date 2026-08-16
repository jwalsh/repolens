"""Alembic environment.

The database URL is read from ``config.Config`` rather than ``alembic.ini``,
so migrations and the application cannot disagree about which database they
are pointed at. ``alembic.ini`` deliberately leaves ``sqlalchemy.url`` empty.

Every model module must be imported here or autogenerate will happily write a
migration that drops the tables it could not see.
"""
import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from config import Config
from repolens.database import db

# Imported for their side effect of registering with db.metadata.
import repolens.models  # noqa: F401

config = context.config

# Precedence: an explicitly configured url wins (that is how tests and
# one-off runs point at a scratch database), then DATABASE_URL read here
# rather than at import time, then the application default.
if not config.get_main_option('sqlalchemy.url'):
    config.set_main_option(
        'sqlalchemy.url',
        os.environ.get('DATABASE_URL') or Config.SQLALCHEMY_DATABASE_URI,
    )

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = db.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=config.get_main_option('sqlalchemy.url'),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={'paramstyle': 'named'},
        # SQLite cannot ALTER most things in place; batch mode rewrites the
        # table instead. Harmless on PostgreSQL, essential for local runs.
        render_as_batch=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix='sqlalchemy.',
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            render_as_batch=True,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
