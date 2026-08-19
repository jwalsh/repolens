"""Ignore resolver tests.

Related work, measured rather than recalled. The same repository -- a root
``.gitignore`` with ``*.log`` and ``!important.log``, a nested
``sub/.gitignore`` with ``!debug.log`` -- put to each tool, with git's
``check-ignore`` as ground truth:

    git    sub/debug.log is NOT ignored   (sub/.gitignore:1:!debug.log)
    rg     agrees -- finds it
    ag     disagrees -- silently drops it
    pathspec, fed only the root .gitignore, also drops it

ripgrep's ``ignore`` crate reimplements the hierarchy correctly. ag does not
honour a nested negation, which for our purposes would silently delete real
source files from the co-change graph. pathspec is not wrong -- it implements
*pattern* semantics correctly and leaves *composition* to the caller, which is
precisely the part that is easy to get wrong.

Hence the design: git resolves, pathspec matches patterns where no authored
answer exists, and we compose nothing hierarchical ourselves.
"""
from __future__ import annotations

import os
import subprocess
import tempfile
import unittest

from hypothesis import given, settings
from hypothesis import strategies as st

from repolens.clones import CloneStore
from repolens.gitcheck import supports_attr_source
from repolens.ignores import (
    GENERATED_PATTERNS,
    VENDORED_PATTERNS,
    Classification,
    IgnoreResolver,
)
from tests._fixtures import git, make_repo


def _write(root: str, relative: str, content: str = 'x\n') -> None:
    path = os.path.join(root, relative)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w') as handle:
        handle.write(content)


class TestHeuristics(unittest.TestCase):
    """Pattern layer only -- no repository needed."""

    def setUp(self):
        self.resolver = IgnoreResolver('/nonexistent', use_attributes=False)

    def _classify(self, path: str) -> Classification:
        return self.resolver.classify([path])[path]

    def test_vendor_directories(self):
        for path in (
            'vendor/lib.go',
            'src/vendor/thing.js',
            'third_party/x/y.c',
            'web/node_modules/left-pad/index.js',
            'static/jquery.min.js',
        ):
            with self.subTest(path=path):
                self.assertTrue(self._classify(path).vendored, path)

    def test_lockfiles_are_generated(self):
        for path in (
            'package-lock.json',
            'poetry.lock',
            'Cargo.lock',
            'go.sum',
            'sub/project/yarn.lock',
            'flake.lock',
        ):
            with self.subTest(path=path):
                self.assertTrue(self._classify(path).generated, path)

    def test_rails_schema_is_generated(self):
        # Earned by auditing rubygems.org, which tracks db/schema.rb: Rails
        # rewrites it from the migrations and commits it by convention.
        for path in ('db/schema.rb', 'db/structure.sql', 'apps/web/db/schema.rb'):
            with self.subTest(path=path):
                self.assertTrue(self._classify(path).generated, path)

    def test_rails_schema_pattern_is_not_overbroad(self):
        # Only the generated pair, not everything under db/ or anything that
        # merely starts with "schema".
        for path in (
            'db/migrate/20260101_add_users.rb',
            'db/seeds.rb',
            'db/schema_helper.rb',
            'app/models/schema.rb',
            'lib/structure.sql',
        ):
            with self.subTest(path=path):
                self.assertFalse(self._classify(path).excluded, path)

    def test_protocol_output_is_generated(self):
        for path in ('api/schema_pb2.py', 'gen/service.pb.go', 'x/thing_pb.js'):
            with self.subTest(path=path):
                self.assertTrue(self._classify(path).generated, path)

    def test_ordinary_source_survives(self):
        for path in (
            'src/main.py',
            'lib/parser.go',
            'README.md',
            'tests/test_thing.py',
            # A directory merely named like a vendor one is not enough.
            'src/vendored_notes.md',
            # Migrations are authored, however mechanical they look.
            'db/migrations/0001_initial.py',
        ):
            with self.subTest(path=path):
                self.assertFalse(self._classify(path).excluded, path)

    def test_extra_patterns_take_effect(self):
        resolver = IgnoreResolver(
            '/nonexistent',
            extra_generated=('**/*.snap',),
            use_attributes=False,
        )

        result = resolver.classify(['tests/__snapshots__/a.snap'])
        self.assertTrue(result['tests/__snapshots__/a.snap'].generated)
        self.assertEqual(result['tests/__snapshots__/a.snap'].source, 'extra')

    def test_filter_preserves_order_and_drops_only_excluded(self):
        paths = ['a.py', 'vendor/b.js', 'c.py', 'poetry.lock', 'd.py']

        self.assertEqual(
            self.resolver.filter(paths), ['a.py', 'c.py', 'd.py']
        )

    @settings(max_examples=200)
    @given(path=st.text(max_size=120))
    def test_never_raises_on_arbitrary_paths(self, path):
        result = self.resolver.classify([path])

        self.assertIn(path, result)
        self.assertIsInstance(result[path].excluded, bool)

    @given(
        paths=st.lists(
            st.text(alphabet='abc/._-', min_size=1, max_size=20),
            max_size=25,
            unique=True,
        )
    )
    def test_filter_is_a_subsequence_of_its_input(self, paths):
        kept = self.resolver.filter(paths)

        self.assertLessEqual(len(kept), len(paths))
        # Order preserved and no invention.
        iterator = iter(paths)
        self.assertTrue(all(item in iterator for item in kept))


class TestAttributes(unittest.TestCase):
    """The authored layer, against a real bare mirror."""

    def setUp(self):
        if not supports_attr_source():
            self.skipTest('git predates check-attr --source')

        self.work_dir = tempfile.TemporaryDirectory()
        self.source = os.path.join(self.work_dir.name, 'source')
        make_repo(self.source, commits=1)

        _write(self.source, 'vendor/dep.js')
        _write(self.source, 'lib/app.js')
        _write(self.source, 'api/schema_pb2.py')
        _write(self.source, 'hand/written.js')
        _write(
            self.source,
            '.gitattributes',
            'vendor/** linguist-vendored\n'
            '*_pb2.py linguist-generated\n'
            # An explicit statement that a heuristic-matching file is authored.
            'hand/written.js -linguist-vendored\n',
        )
        git('add', '-A', cwd=self.source)
        git('commit', '-q', '-m', 'attributes', cwd=self.source)

        self.store = CloneStore(root=os.path.join(self.work_dir.name, 'clones'))
        self.clone_path = self.store.ensure(self.source).path
        self.resolver = IgnoreResolver(self.clone_path)

    def tearDown(self):
        self.work_dir.cleanup()

    def test_attributes_are_read_from_a_bare_mirror(self):
        # No working tree anywhere in this test.
        is_bare = subprocess.run(
            ['git', '--git-dir', str(self.clone_path), 'rev-parse',
             '--is-bare-repository'],
            capture_output=True, text=True, check=True,
        ).stdout.strip()
        self.assertEqual(is_bare, 'true')

        result = self.resolver.classify(['vendor/dep.js', 'api/schema_pb2.py'])

        self.assertTrue(result['vendor/dep.js'].vendored)
        self.assertEqual(result['vendor/dep.js'].source, 'gitattributes')
        self.assertTrue(result['api/schema_pb2.py'].generated)
        self.assertEqual(result['api/schema_pb2.py'].source, 'gitattributes')

    def test_unmarked_source_survives(self):
        result = self.resolver.classify(['lib/app.js'])

        self.assertFalse(result['lib/app.js'].excluded)
        self.assertEqual(result['lib/app.js'].source, 'none')

    def test_one_git_process_per_call_not_per_path(self):
        paths = [f'lib/file{index}.js' for index in range(50)]

        calls: list[list[str]] = []
        original = subprocess.run

        def counting_run(argv, *args, **kwargs):
            calls.append(argv)
            return original(argv, *args, **kwargs)

        subprocess.run = counting_run
        try:
            self.resolver.classify(paths)
        finally:
            subprocess.run = original

        check_attr_calls = [c for c in calls if 'check-attr' in c]
        self.assertEqual(len(check_attr_calls), 1)

    def test_results_are_cached_per_revision(self):
        self.resolver.classify(['lib/app.js'])

        calls: list[list[str]] = []
        original = subprocess.run

        def counting_run(argv, *args, **kwargs):
            calls.append(argv)
            return original(argv, *args, **kwargs)

        subprocess.run = counting_run
        try:
            self.resolver.classify(['lib/app.js'])
        finally:
            subprocess.run = original

        self.assertEqual([c for c in calls if 'check-attr' in c], [])

    def test_the_same_path_classifies_differently_across_revisions(self):
        """The anachronism, demonstrated.

        Filtering a ten-year co-change window through HEAD's rules gives the
        wrong answer for the years before those rules existed. This is why
        `classify` takes a revision instead of assuming HEAD.
        """
        old_head = git('rev-parse', 'HEAD', cwd=self.source)

        # Narrow the attributes: _pb2.py is no longer declared generated.
        _write(self.source, '.gitattributes', 'vendor/** linguist-vendored\n')
        git('add', '-A', cwd=self.source)
        git('commit', '-q', '-m', 'narrow attributes', cwd=self.source)
        new_head = git('rev-parse', 'HEAD', cwd=self.source)
        self.store.ensure(self.source)

        at_old = self.resolver.classify(['api/schema_pb2.py'], revision=old_head)
        at_new = self.resolver.classify(['api/schema_pb2.py'], revision=new_head)

        self.assertEqual(at_old['api/schema_pb2.py'].source, 'gitattributes')
        # At the newer revision the attribute is gone, so only the heuristic
        # remains -- a different answer, from a weaker source.
        self.assertEqual(at_new['api/schema_pb2.py'].source, 'heuristic')

    def test_a_negated_attribute_does_not_resurrect_the_heuristic(self):
        # `hand/written.js` is explicitly -linguist-vendored. It matches no
        # heuristic either, so it must survive. The interesting case is that
        # an author saying "this is mine" is never overridden.
        result = self.resolver.classify(['hand/written.js'])

        self.assertFalse(result['hand/written.js'].excluded)

    def test_stats_report_whether_the_authored_layer_was_available(self):
        stats = self.resolver.stats(
            ['vendor/dep.js', 'lib/app.js', 'poetry.lock']
        )

        self.assertTrue(stats.attributes_available)
        self.assertEqual(stats.total, 3)
        self.assertEqual(stats.excluded, 2)
        self.assertEqual(stats.by_source['gitattributes'], 1)
        self.assertEqual(stats.by_source['heuristic'], 1)

    def test_heuristics_only_mode_reports_itself(self):
        resolver = IgnoreResolver(self.clone_path, use_attributes=False)

        stats = resolver.stats(['vendor/dep.js'])

        self.assertFalse(stats.attributes_available)


class TestAttributeValueSpellings(unittest.TestCase):
    """`foo`, `foo=true` and `foo=false` are three different git values.

    kubernetes/kubernetes writes every linguist-generated rule as `=true`.
    Matching only the bare "set" spelling silently drops the authored layer
    for those repositories -- the exact failure this module exists to avoid.
    """

    def setUp(self):
        if not supports_attr_source():
            self.skipTest('git predates check-attr --source')

        self.work_dir = tempfile.TemporaryDirectory()
        self.source = os.path.join(self.work_dir.name, 'source')
        make_repo(self.source, commits=1)

        _write(self.source, 'a/bare.go')
        _write(self.source, 'b/istrue.go')
        _write(self.source, 'c/isfalse.go')
        _write(self.source, 'd/unset.go')
        _write(
            self.source,
            '.gitattributes',
            'a/bare.go linguist-generated\n'
            'b/istrue.go linguist-generated=true\n'
            'c/isfalse.go linguist-generated=false\n'
            'd/unset.go -linguist-generated\n',
        )
        git('add', '-A', cwd=self.source)
        git('commit', '-q', '-m', 'attribute spellings', cwd=self.source)

        store = CloneStore(root=os.path.join(self.work_dir.name, 'clones'))
        self.resolver = IgnoreResolver(store.ensure(self.source).path)

    def tearDown(self):
        self.work_dir.cleanup()

    def test_bare_and_true_both_mean_generated(self):
        result = self.resolver.classify(['a/bare.go', 'b/istrue.go'])

        self.assertTrue(result['a/bare.go'].generated, 'bare spelling')
        self.assertTrue(result['b/istrue.go'].generated, '=true spelling')
        for path in ('a/bare.go', 'b/istrue.go'):
            self.assertEqual(result[path].source, 'gitattributes')

    def test_false_and_unset_mean_authored(self):
        result = self.resolver.classify(['c/isfalse.go', 'd/unset.go'])

        # An author saying "this is mine", in either spelling.
        self.assertFalse(result['c/isfalse.go'].excluded, '=false spelling')
        self.assertFalse(result['d/unset.go'].excluded, '-attr spelling')


class TestPathsWithAwkwardCharacters(unittest.TestCase):
    def setUp(self):
        if not supports_attr_source():
            self.skipTest('git predates check-attr --source')

        self.work_dir = tempfile.TemporaryDirectory()
        self.source = os.path.join(self.work_dir.name, 'source')
        make_repo(self.source, commits=1)
        _write(self.source, 'a file with spaces.js')
        _write(self.source, "quote'name.js")
        _write(self.source, '.gitattributes', '*.js linguist-vendored\n')
        git('add', '-A', cwd=self.source)
        git('commit', '-q', '-m', 'awkward paths', cwd=self.source)

        store = CloneStore(root=os.path.join(self.work_dir.name, 'clones'))
        self.resolver = IgnoreResolver(store.ensure(self.source).path)

    def tearDown(self):
        self.work_dir.cleanup()

    def test_nul_delimited_protocol_survives_spaces_and_quotes(self):
        # The line-oriented check-attr output mangles these; -z does not.
        paths = ['a file with spaces.js', "quote'name.js"]

        result = self.resolver.classify(paths)

        for path in paths:
            with self.subTest(path=path):
                self.assertTrue(result[path].vendored, path)
                self.assertEqual(result[path].source, 'gitattributes')


class TestPatternListHygiene(unittest.TestCase):
    def test_no_duplicate_patterns(self):
        for name, patterns in (
            ('VENDORED', VENDORED_PATTERNS), ('GENERATED', GENERATED_PATTERNS)
        ):
            with self.subTest(list=name):
                self.assertEqual(len(patterns), len(set(patterns)))

    def test_the_two_lists_do_not_overlap(self):
        self.assertEqual(
            set(VENDORED_PATTERNS) & set(GENERATED_PATTERNS), set()
        )


if __name__ == '__main__':
    unittest.main()
