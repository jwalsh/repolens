"""Clone store tests.

The path-derivation properties are property-based rather than example-based
on purpose. A repository URL is attacker-controlled on every endpoint that
reaches the clone store, so "does any string escape the root" is a question
about the whole input space, and picking three examples answers a different
question.
"""
from __future__ import annotations

import os
import subprocess
import tempfile
import unittest

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from repolens.clones import CloneError, CloneStore, _slugify
from tests._fixtures import add_commit, make_repo

# Deliberately hostile: separators, traversal, dotfiles, NUL-adjacent control
# characters, and the empty string all reach _slugify in production.
URLS = st.one_of(
    st.text(max_size=120),
    st.text(alphabet='./\\-_ .', max_size=30),
    st.sampled_from([
        '',
        '.',
        '..',
        '../../etc/passwd',
        '/../..',
        'https://github.com/a/b.git',
        'git@github.com:a/b.git',
        'file:///tmp/x',
        '~/x',
        '-oProxyCommand=touch /tmp/pwned',
    ]),
)


class TestPathDerivation(unittest.TestCase):
    """path_for is a pure function; these need no filesystem."""

    def setUp(self):
        self.root_dir = tempfile.TemporaryDirectory()
        self.store = CloneStore(root=self.root_dir.name)

    def tearDown(self):
        self.root_dir.cleanup()

    @given(repo_url=URLS)
    def test_path_is_always_contained_in_root(self, repo_url):
        path = self.store.path_for(repo_url)

        self.assertEqual(path.parent, self.store.root)
        self.assertEqual(
            path.resolve().parent,
            self.store.root.resolve(),
            msg=f'{repo_url!r} escaped the clone root',
        )

    @given(repo_url=URLS)
    def test_path_is_deterministic(self, repo_url):
        self.assertEqual(
            self.store.path_for(repo_url), self.store.path_for(repo_url)
        )

    @given(first=URLS, second=URLS)
    def test_distinct_urls_get_distinct_paths(self, first, second):
        if first == second:
            return
        self.assertNotEqual(
            self.store.path_for(first), self.store.path_for(second)
        )

    @given(repo_url=URLS)
    def test_slug_never_traverses(self, repo_url):
        slug = _slugify(repo_url)

        self.assertNotIn('/', slug)
        self.assertNotIn(os.sep, slug)
        self.assertNotIn('\x00', slug)
        self.assertNotEqual(slug, '')
        self.assertFalse(set(slug) <= {'.'})


class TestUrlValidation(unittest.TestCase):
    def setUp(self):
        self.root_dir = tempfile.TemporaryDirectory()
        self.store = CloneStore(root=self.root_dir.name)

    def tearDown(self):
        self.root_dir.cleanup()

    def test_rejects_ext_transport(self):
        # git's ext:: transport runs a command out of the URL.
        with self.assertRaises(CloneError):
            self.store.ensure('ext::sh -c touch% /tmp/pwned')

    def test_rejects_leading_dash(self):
        with self.assertRaises(CloneError):
            self.store.ensure('--upload-pack=touch /tmp/pwned')

    def test_rejects_empty(self):
        with self.assertRaises(CloneError):
            self.store.ensure('   ')


class TestEnsure(unittest.TestCase):
    def setUp(self):
        self.work_dir = tempfile.TemporaryDirectory()
        self.root = os.path.join(self.work_dir.name, 'clones')
        self.store = CloneStore(root=self.root)
        self.source = make_repo(os.path.join(self.work_dir.name, 'source'))

    def tearDown(self):
        self.work_dir.cleanup()

    def test_first_ensure_clones(self):
        stats = self.store.ensure(self.source)

        self.assertTrue(stats.was_cloned)
        self.assertEqual(stats.commit_count, 2)
        self.assertTrue(self.store.exists(self.source))
        self.assertGreater(stats.bytes_on_disk, 0)

    def test_clone_is_bare(self):
        # The design commitment: mirrors, not working trees. Blame against an
        # explicit revision works without a checkout, so a checkout is cost.
        self.store.ensure(self.source)
        path = self.store.path_for(self.source)

        is_bare = subprocess.run(
            ['git', '--git-dir', str(path), 'rev-parse', '--is-bare-repository'],
            capture_output=True, text=True, check=True,
        ).stdout.strip()

        self.assertEqual(is_bare, 'true')

    def test_blame_works_in_the_mirror(self):
        self.store.ensure(self.source)
        path = self.store.path_for(self.source)

        blame = subprocess.run(
            ['git', '--git-dir', str(path), 'blame', '--line-porcelain',
             'HEAD', '--', 'file0.txt'],
            capture_output=True, text=True, check=True,
        ).stdout

        self.assertIn('author Test', blame)

    def test_ensure_is_idempotent(self):
        first = self.store.ensure(self.source)
        second = self.store.ensure(self.source)

        self.assertTrue(first.was_cloned)
        self.assertFalse(second.was_cloned)
        self.assertEqual(first.path, second.path)
        self.assertEqual(first.head_sha, second.head_sha)

    def test_ensure_fetches_new_commits(self):
        self.store.ensure(self.source)
        new_sha = add_commit(self.source)

        stats = self.store.ensure(self.source)

        self.assertFalse(stats.was_cloned)
        self.assertEqual(stats.head_sha, new_sha)
        self.assertEqual(stats.commit_count, 3)

    def test_unshallows_a_shallow_clone(self):
        shallow = os.path.join(self.work_dir.name, 'shallow.git')
        subprocess.run(
            ['git', 'clone', '--mirror', '--depth', '1', '--quiet',
             f'file://{self.source}', shallow],
            check=True, capture_output=True,
        )
        os.makedirs(self.root, exist_ok=True)
        os.replace(shallow, str(self.store.path_for(self.source)))

        stats = self.store.ensure(self.source)

        self.assertTrue(stats.was_unshallowed)
        self.assertEqual(stats.commit_count, 2)

    def test_evict_removes_the_mirror(self):
        self.store.ensure(self.source)

        self.assertTrue(self.store.evict(self.source))
        self.assertFalse(self.store.exists(self.source))
        self.assertFalse(self.store.evict(self.source))

    def test_head_sha_requires_a_mirror(self):
        with self.assertRaises(CloneError):
            self.store.head_sha(self.source)

    def test_disk_usage_counts_only_the_root(self):
        self.assertEqual(self.store.disk_usage_bytes(), 0)
        self.store.ensure(self.source)
        self.assertGreater(self.store.disk_usage_bytes(), 0)
        self.assertEqual(len(self.store.list_clones()), 1)

    def test_failed_clone_leaves_no_partial_mirror(self):
        missing = os.path.join(self.work_dir.name, 'not-a-repo')

        with self.assertRaises(CloneError):
            self.store.ensure(missing)

        self.assertFalse(self.store.path_for(missing).exists())


class TestEnsureProperties(unittest.TestCase):
    """Idempotence over a generated call sequence rather than two calls."""

    @settings(
        max_examples=15,
        deadline=None,
        suppress_health_check=[HealthCheck.function_scoped_fixture],
    )
    @given(extra_calls=st.integers(min_value=0, max_value=4))
    def test_repeated_ensure_never_changes_head(self, extra_calls):
        with tempfile.TemporaryDirectory() as work_dir:
            source = make_repo(os.path.join(work_dir, 'source'))
            store = CloneStore(root=os.path.join(work_dir, 'clones'))

            baseline = store.ensure(source)
            for _ in range(extra_calls):
                repeat = store.ensure(source)
                self.assertEqual(repeat.head_sha, baseline.head_sha)
                self.assertEqual(repeat.path, baseline.path)
                self.assertFalse(repeat.was_cloned)

            self.assertEqual(len(store.list_clones()), 1)


if __name__ == '__main__':
    unittest.main()
