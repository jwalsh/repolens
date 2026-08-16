import os
import subprocess
import tempfile
import unittest

from repolens.packager import package_repository
from repolens.models import Repository
from repolens.database import db
from main import create_app


def _make_fixture_repo(path: str) -> None:
    """Build a tiny local git repo so the packager test needs no network."""
    def run(*argv: str) -> None:
        subprocess.run(argv, cwd=path, check=True, capture_output=True)

    os.makedirs(path, exist_ok=True)
    run('git', 'init', '-q', '-b', 'main')
    run('git', 'config', 'user.email', 'test@example.com')
    run('git', 'config', 'user.name', 'Test')

    with open(os.path.join(path, 'alpha.py'), 'w') as handle:
        handle.write('print("alpha")\n')
    run('git', 'add', 'alpha.py')
    run('git', 'commit', '-q', '-m', 'add alpha')

    with open(os.path.join(path, 'beta.js'), 'w') as handle:
        handle.write('console.log("beta");\n')
    run('git', 'add', 'beta.js')
    run('git', 'commit', '-q', '-m', 'add beta')


class TestPackager(unittest.TestCase):
    def setUp(self):
        # In-memory, so the suite never writes site.db into the working tree.
        self.flask_app = create_app(SQLALCHEMY_DATABASE_URI='sqlite:///:memory:')
        self.app_context = self.flask_app.app_context()
        self.app_context.push()
        db.create_all()

        self.fixture_dir = tempfile.TemporaryDirectory()
        self.fixture_path = os.path.join(self.fixture_dir.name, 'fixture_repo')
        _make_fixture_repo(self.fixture_path)

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.app_context.pop()
        self.fixture_dir.cleanup()

    def test_package_repository(self):
        repo_id, error = package_repository(self.fixture_path)

        self.assertIsNone(error)
        self.assertIsNotNone(repo_id)

        repository = db.session.get(Repository, repo_id)
        self.assertIsNotNone(repository)
        self.assertEqual(repository.url, self.fixture_path)
        self.assertIsNotNone(repository.packaged_data)
        self.assertIn('files', repository.packaged_data)
        self.assertIn('commits', repository.packaged_data)
        self.assertIn('branches', repository.packaged_data)
        self.assertEqual(len(repository.packaged_data['commits']), 2)

    def test_package_repository_rejects_bad_url(self):
        repo_id, error = package_repository(
            os.path.join(self.fixture_dir.name, 'does_not_exist')
        )

        self.assertIsNone(repo_id)
        self.assertIsNotNone(error)


if __name__ == '__main__':
    unittest.main()
