"""Migration tests.

The load-bearing one is ``test_models_and_migrations_do_not_drift``. RepoLens
managed its schema with ``db.create_all()``, which silently does nothing to an
existing table, so a model change and a deployed database could disagree
indefinitely with no signal. RFC 028 phasing adds at least three schema
versions on top of that.

This test turns drift into a failing build: add a column to a model without a
migration and it fails here, naming the column.
"""
from __future__ import annotations

import os
import tempfile
import unittest

from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config as AlembicConfig
from alembic.migration import MigrationContext
from sqlalchemy import create_engine, inspect

from repolens.database import db
import repolens.models  # noqa: F401 - registers models with db.metadata

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _alembic_config(database_url: str) -> AlembicConfig:
    config = AlembicConfig(os.path.join(REPO_ROOT, 'alembic.ini'))
    config.set_main_option('script_location', os.path.join(REPO_ROOT, 'migrations'))
    config.set_main_option('sqlalchemy.url', database_url)
    return config


class TestMigrations(unittest.TestCase):
    def setUp(self):
        self.work_dir = tempfile.TemporaryDirectory()
        self.database_path = os.path.join(self.work_dir.name, 'migrations.db')
        self.database_url = f'sqlite:///{self.database_path}'
        # env.py reads config.Config, which reads DATABASE_URL.
        self._saved_url = os.environ.get('DATABASE_URL')
        os.environ['DATABASE_URL'] = self.database_url

    def tearDown(self):
        if self._saved_url is None:
            os.environ.pop('DATABASE_URL', None)
        else:
            os.environ['DATABASE_URL'] = self._saved_url
        self.work_dir.cleanup()

    def test_upgrade_head_creates_the_schema(self):
        command.upgrade(_alembic_config(self.database_url), 'head')

        engine = create_engine(self.database_url)
        tables = set(inspect(engine).get_table_names())
        engine.dispose()

        self.assertIn('repository', tables)
        self.assertIn('analysis', tables)

    def test_downgrade_to_base_is_clean(self):
        config = _alembic_config(self.database_url)
        command.upgrade(config, 'head')
        command.downgrade(config, 'base')

        engine = create_engine(self.database_url)
        tables = set(inspect(engine).get_table_names())
        engine.dispose()

        self.assertNotIn('repository', tables)
        self.assertNotIn('analysis', tables)

    def test_models_and_migrations_do_not_drift(self):
        command.upgrade(_alembic_config(self.database_url), 'head')

        engine = create_engine(self.database_url)
        try:
            with engine.connect() as connection:
                context = MigrationContext.configure(
                    connection, opts={'compare_type': True}
                )
                differences = compare_metadata(context, db.metadata)
        finally:
            engine.dispose()

        self.assertEqual(
            differences,
            [],
            msg=(
                'Models and migrations have drifted. Run:\n'
                '  alembic revision --autogenerate -m "<what changed>"\n'
                f'Pending: {differences}'
            ),
        )

    def test_foreign_key_targets_the_real_table_name(self):
        # RFC 028 §19.2: the spec's schema used ForeignKey("repo.id"), but
        # flask-sqlalchemy names the table `repository`. Pin it so the
        # provenance tables are written against the right target.
        command.upgrade(_alembic_config(self.database_url), 'head')

        engine = create_engine(self.database_url)
        foreign_keys = inspect(engine).get_foreign_keys('analysis')
        engine.dispose()

        self.assertEqual(len(foreign_keys), 1)
        self.assertEqual(foreign_keys[0]['referred_table'], 'repository')


if __name__ == '__main__':
    unittest.main()
