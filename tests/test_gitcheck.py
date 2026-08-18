"""Git version requirement.

The behaviour under test is a refusal. RepoLens has twice been bitten by
something degrading quietly -- `unittest discover` reporting OK on zero
tests, and the ignore resolver dropping its authored layer -- and both looked
exactly like success. An old git must stop the process, not change the
answers.
"""
from __future__ import annotations

import unittest
from unittest import mock

from repolens.gitcheck import (
    MIN_GIT,
    GitMissing,
    GitTooOld,
    git_version,
    parse_version,
    require_git,
    supports_attr_source,
)


class TestParseVersion(unittest.TestCase):
    def test_standard_output(self):
        self.assertEqual(parse_version('git version 2.49.0'), (2, 49, 0))

    def test_two_component_version(self):
        self.assertEqual(parse_version('git version 2.40'), (2, 40, 0))

    def test_vendor_suffixed_output(self):
        # Apple ships `git version 2.39.5 (Apple Git-154)`.
        self.assertEqual(
            parse_version('git version 2.39.5 (Apple Git-154)'), (2, 39, 5)
        )

    def test_unparseable_is_none_not_optimistic(self):
        # None means "treated as too old" downstream. An unreadable version
        # is not evidence of a new git.
        self.assertIsNone(parse_version('git version banana'))
        self.assertIsNone(parse_version(''))


class TestSupportsAttrSource(unittest.TestCase):
    def test_boundary(self):
        self.assertTrue(supports_attr_source((2, 40, 0)))
        self.assertFalse(supports_attr_source((2, 39, 9)))

    def test_newer_majors(self):
        self.assertTrue(supports_attr_source((3, 0, 0)))

    def test_undetectable_git_is_unsupported(self):
        # Passing None means "detect", so the unknown-version case has to be
        # driven through git_version rather than through the argument.
        with mock.patch('repolens.gitcheck.git_version', return_value=None):
            self.assertFalse(supports_attr_source())

    def test_omitted_argument_detects_the_real_git(self):
        self.assertTrue(supports_attr_source())


class TestRequireGit(unittest.TestCase):
    def test_passes_on_this_machine(self):
        version = require_git()

        self.assertGreaterEqual(version[:2], MIN_GIT)

    def test_raises_on_old_git(self):
        with mock.patch('repolens.gitcheck.git_version', return_value=(2, 39, 5)):
            with self.assertRaises(GitTooOld) as raised:
                require_git()

        message = str(raised.exception)
        # The error has to be actionable: what was found, what is needed, and
        # the escape hatch.
        self.assertIn('2.39.5', message)
        self.assertIn('2.40', message)
        self.assertIn('use_attributes=False', message)

    def test_raises_when_git_is_absent(self):
        with mock.patch('repolens.gitcheck.git_version', return_value=None):
            with self.assertRaises(GitMissing):
                require_git()

    def test_exact_minimum_is_accepted(self):
        with mock.patch('repolens.gitcheck.git_version', return_value=(2, 40, 0)):
            self.assertEqual(require_git(), (2, 40, 0))


class TestResolverEnforcement(unittest.TestCase):
    def test_resolver_refuses_to_construct_on_old_git(self):
        from repolens.ignores import IgnoreResolver

        with mock.patch('repolens.gitcheck.git_version', return_value=(2, 39, 5)):
            with self.assertRaises(GitTooOld):
                IgnoreResolver('/nonexistent')

    def test_heuristics_only_mode_is_still_allowed_on_old_git(self):
        # The degraded mode remains available -- but only by asking for it.
        from repolens.ignores import IgnoreResolver

        with mock.patch('repolens.gitcheck.git_version', return_value=(2, 39, 5)):
            resolver = IgnoreResolver('/nonexistent', use_attributes=False)

        self.assertFalse(resolver.attributes_available)
        self.assertTrue(resolver.classify(['vendor/x.js'])['vendor/x.js'].vendored)


class TestApplicationStartup(unittest.TestCase):
    def test_create_app_refuses_on_old_git(self):
        from main import create_app

        with mock.patch('repolens.gitcheck.git_version', return_value=(2, 39, 5)):
            with self.assertRaises(GitTooOld):
                create_app(SQLALCHEMY_DATABASE_URI='sqlite:///:memory:')

    def test_real_git_version_is_readable(self):
        self.assertIsNotNone(git_version())


if __name__ == '__main__':
    unittest.main()
