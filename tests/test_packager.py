import os
import tempfile
import unittest
from unittest import mock

from repolens.packager import (
    list_branches,
    list_files,
    package_repository,
)
from repolens.models import Repository
from repolens.database import db
from main import create_app
from tests._fixtures import add_commit, make_repo


class TestPackager(unittest.TestCase):
    def setUp(self):
        self.work_dir = tempfile.TemporaryDirectory()
        # In-memory DB and a scratch clone root, so the suite writes neither
        # site.db nor .clones into the working tree.
        self.flask_app = create_app(
            SQLALCHEMY_DATABASE_URI='sqlite:///:memory:',
            CLONE_ROOT=os.path.join(self.work_dir.name, 'clones'),
        )
        self.app_context = self.flask_app.app_context()
        self.app_context.push()
        db.create_all()

        self.fixture_path = make_repo(
            os.path.join(self.work_dir.name, 'fixture_repo')
        )

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.app_context.pop()
        self.work_dir.cleanup()

    def test_package_repository(self):
        repo_id, error = package_repository(self.fixture_path)

        self.assertIsNone(error)
        self.assertIsNotNone(repo_id)

        repository = db.session.get(Repository, repo_id)
        self.assertIsNotNone(repository)
        self.assertEqual(repository.url, self.fixture_path)

        packaged = repository.packaged_data
        self.assertIn('files', packaged)
        self.assertIn('commits', packaged)
        self.assertIn('branches', packaged)
        self.assertEqual(packaged['commit_count'], 2)
        self.assertEqual(len(packaged['commits']), 2)
        self.assertFalse(packaged['commits_truncated'])
        self.assertEqual(len(packaged['head_sha']), 40)
        self.assertEqual(packaged['branches'], ['main'])

    def test_package_repository_rejects_bad_url(self):
        repo_id, error = package_repository(
            os.path.join(self.work_dir.name, 'does_not_exist')
        )

        self.assertIsNone(repo_id)
        self.assertIsNotNone(error)

    def test_file_listing_excludes_git_internals(self):
        # The os.walk implementation counted .git/hooks/*.sample and pack
        # files as repository files. A bare mirror has no working tree, so
        # ls-tree is the only way to answer the question -- and the right one.
        repo_id, _ = package_repository(self.fixture_path)
        packaged = db.session.get(Repository, repo_id).packaged_data

        paths = {entry['path'] for entry in packaged['files']}

        self.assertEqual(paths, {'file0.txt', 'file1.txt'})
        self.assertFalse(any('.git' in path for path in paths))
        self.assertFalse(any(path.endswith('.sample') for path in paths))
        self.assertTrue(all(entry['size'] > 0 for entry in packaged['files']))

    def test_repackaging_fetches_instead_of_recloning(self):
        first_id, _ = package_repository(self.fixture_path)
        new_sha = add_commit(self.fixture_path)

        second_id, _ = package_repository(self.fixture_path)

        self.assertNotEqual(first_id, second_id)
        second = db.session.get(Repository, second_id).packaged_data
        self.assertEqual(second['head_sha'], new_sha)
        self.assertEqual(second['commit_count'], 3)

    def test_embedded_commits_are_capped(self):
        source = make_repo(os.path.join(self.work_dir.name, 'many'), commits=6)

        with mock.patch('repolens.packager.EMBEDDED_COMMIT_LIMIT', 2):
            repo_id, error = package_repository(source)

        self.assertIsNone(error)
        packaged = db.session.get(Repository, repo_id).packaged_data
        # commit_count stays exact; only the denormalised list is bounded.
        self.assertEqual(packaged['commit_count'], 6)
        self.assertEqual(len(packaged['commits']), 2)
        self.assertTrue(packaged['commits_truncated'])

    def test_commit_count_analysis_uses_the_exact_total(self):
        from repolens.analyzer import analyze_repository
        from repolens.models import Analysis

        source = make_repo(os.path.join(self.work_dir.name, 'many'), commits=6)
        with mock.patch('repolens.packager.EMBEDDED_COMMIT_LIMIT', 2):
            repo_id, _ = package_repository(source)

        analysis_id = analyze_repository(repo_id, 'commit_count')

        # Not 2. Truncating the embedded list must not silently truncate the
        # answer to "how many commits does this repository have".
        analysis = db.session.get(Analysis, analysis_id)
        self.assertEqual(analysis.result['total_commits'], 6)


class TestGitReaders(unittest.TestCase):
    """The ls-tree/for-each-ref readers, exercised against a bare mirror."""

    def setUp(self):
        from repolens.clones import CloneStore

        self.work_dir = tempfile.TemporaryDirectory()
        source = make_repo(os.path.join(self.work_dir.name, 'source'))
        store = CloneStore(root=os.path.join(self.work_dir.name, 'clones'))
        self.clone_path = store.ensure(source).path

    def tearDown(self):
        self.work_dir.cleanup()

    def test_list_files_reports_sizes(self):
        files = list_files(self.clone_path)

        self.assertEqual(len(files), 2)
        for entry in files:
            self.assertGreater(entry['size'], 0)

    def test_list_branches(self):
        self.assertEqual(list_branches(self.clone_path), ['main'])


if __name__ == '__main__':
    unittest.main()
