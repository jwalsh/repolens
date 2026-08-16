"""Forge client tests. No network.

The property worth generating inputs for is the conservatism of
``pr_number_from_commit``. Commit bodies are full of ``#123`` and only some of
those are pull requests; under spec invariant I1 a wrong association produces
an evidence span pointing at prose the author never wrote about this commit,
which is a worse failure than having no claim at all. So the test asserts the
*negative*: no issue-reference form is ever read as a pull request.
"""
from __future__ import annotations

import string
import unittest

from hypothesis import given, settings
from hypothesis import strategies as st

from repolens.forge import (
    ForgeError,
    GitHubForge,
    RateLimited,
    RepoRef,
    parse_link_header,
    parse_repo_ref,
    pr_number_from_commit,
)


class FakeResponse:
    def __init__(self, status_code=200, payload=None, headers=None, text=''):
        self.status_code = status_code
        self._payload = payload if payload is not None else []
        self.headers = headers or {}
        self.text = text

    def json(self):
        return self._payload


class FakeSession:
    """Records requests and replays a scripted list of responses."""

    def __init__(self, responses):
        self._responses = list(responses)
        self.requests: list[tuple[str, dict]] = []

    def get(self, url, headers, timeout):
        self.requests.append((url, headers))
        if not self._responses:
            raise AssertionError(f'unexpected request to {url}')
        return self._responses.pop(0)


class TestRepoRefParsing(unittest.TestCase):
    def test_https_url(self):
        self.assertEqual(
            parse_repo_ref('https://github.com/psf/requests.git'),
            RepoRef('psf', 'requests'),
        )

    def test_https_url_without_git_suffix(self):
        self.assertEqual(
            parse_repo_ref('https://github.com/psf/requests'),
            RepoRef('psf', 'requests'),
        )

    def test_ssh_url(self):
        self.assertEqual(
            parse_repo_ref('git@github.com:psf/requests.git'),
            RepoRef('psf', 'requests'),
        )

    def test_local_path_is_not_a_forge_url(self):
        # The test fixtures are local paths. Returning a bogus RepoRef for
        # them would send requests to api.github.com/repos/tmp/fixture.
        self.assertIsNone(parse_repo_ref('/tmp/fixture_repo'))
        self.assertIsNone(parse_repo_ref('file:///tmp/fixture_repo'))
        self.assertIsNone(parse_repo_ref(''))
        self.assertIsNone(parse_repo_ref('https://github.com/onlyowner'))

    @given(
        owner=st.text(alphabet=string.ascii_letters + string.digits + '-', min_size=1, max_size=20),
        name=st.text(alphabet=string.ascii_letters + string.digits + '-._', min_size=1, max_size=20),
    )
    def test_https_round_trip(self, owner, name):
        if name.endswith('.git'):
            return
        ref = parse_repo_ref(f'https://github.com/{owner}/{name}.git')

        self.assertIsNotNone(ref)
        self.assertEqual(ref.slug, f'{owner}/{name}')


class TestPullRequestResolution(unittest.TestCase):
    def test_merge_commit(self):
        self.assertEqual(
            pr_number_from_commit('Merge pull request #123 from fork/branch'), 123
        )

    def test_squash_merge(self):
        self.assertEqual(pr_number_from_commit('Fix the parser (#456)'), 456)

    def test_gitlab_merge_request(self):
        self.assertEqual(
            pr_number_from_commit(
                "Merge branch 'fix' into 'main'",
                "Fix the thing\n\nSee merge request group/project!789",
            ),
            789,
        )

    def test_revert_of_a_squash_merge_is_not_that_pull_request(self):
        # The revert is its own change with its own PR. Attributing the
        # original PR's prose to it would be wrong in a way that reads right.
        self.assertIsNone(
            pr_number_from_commit('Revert "Fix the parser (#456)"')
        )

    def test_issue_references_are_not_pull_requests(self):
        for subject in (
            'Fixes #123',
            'Closes #123',
            'Resolves #123',
            'Fix crash, see #123 for context',
            'Bump deps #123',
            'refs #123',
        ):
            with self.subTest(subject=subject):
                self.assertIsNone(pr_number_from_commit(subject))

    def test_merge_pull_request_must_start_the_subject(self):
        # "...which reverts Merge pull request #1" is not that merge.
        self.assertIsNone(
            pr_number_from_commit('Revert Merge pull request #1 from a/b')
        )

    @settings(max_examples=200)
    @given(
        keyword=st.sampled_from([
            'Fixes', 'Fixed', 'Closes', 'Closed', 'Resolves', 'Resolved',
            'See', 'Refs', 'Ref', 'Related to', 'Part of', 'Reverts',
        ]),
        number=st.integers(min_value=1, max_value=999_999),
        prefix=st.text(alphabet=string.ascii_letters + ' ,.', max_size=40),
        suffix=st.text(alphabet=string.ascii_letters + ' ,.', max_size=40),
    )
    def test_no_issue_reference_is_ever_read_as_a_pull_request(
        self, keyword, number, prefix, suffix
    ):
        subject = f'{prefix}{keyword} #{number}{suffix}'.strip()

        # Skip anything that happens to generate a genuinely accepted form.
        if subject.startswith('Merge pull request #') or subject.endswith(')'):
            return

        self.assertIsNone(
            pr_number_from_commit(subject),
            msg=f'issue reference misread as a PR: {subject!r}',
        )

    @given(subject=st.text(max_size=200), body=st.text(max_size=400))
    def test_never_raises_on_arbitrary_text(self, subject, body):
        result = pr_number_from_commit(subject, body)

        self.assertTrue(result is None or result > 0)


class TestLinkHeader(unittest.TestCase):
    def test_extracts_next(self):
        header = (
            '<https://api.github.com/repos/a/b/pulls?page=2>; rel="next", '
            '<https://api.github.com/repos/a/b/pulls?page=9>; rel="last"'
        )

        links = parse_link_header(header)

        self.assertEqual(links['next'], 'https://api.github.com/repos/a/b/pulls?page=2')
        self.assertEqual(links['last'], 'https://api.github.com/repos/a/b/pulls?page=9')

    def test_absent_header(self):
        self.assertEqual(parse_link_header(None), {})
        self.assertEqual(parse_link_header(''), {})

    @given(header=st.text(max_size=200))
    def test_never_raises_on_junk(self, header):
        self.assertIsInstance(parse_link_header(header), dict)


class TestPagination(unittest.TestCase):
    def _pr(self, number):
        return {
            'number': number,
            'title': f'PR {number}',
            'body': f'body {number}',
            'user': {'login': 'someone'},
            'state': 'closed',
            'merged_at': '2026-01-01T00:00:00Z',
            'merge_commit_sha': 'a' * 40,
            'html_url': f'https://github.com/a/b/pull/{number}',
        }

    def test_follows_the_next_link(self):
        session = FakeSession([
            FakeResponse(
                payload=[self._pr(1), self._pr(2)],
                headers={'link': '<https://api.example/page2>; rel="next"'},
            ),
            FakeResponse(payload=[self._pr(3)], headers={}),
        ])
        forge = GitHubForge(token='t', session=session, base_url='https://api.example')

        pulls = list(forge.iter_pull_requests(RepoRef('a', 'b')))

        self.assertEqual([pull.number for pull in pulls], [1, 2, 3])
        self.assertEqual(len(session.requests), 2)
        self.assertEqual(session.requests[1][0], 'https://api.example/page2')

    def test_requests_a_full_page(self):
        session = FakeSession([FakeResponse(payload=[], headers={})])
        forge = GitHubForge(token='t', session=session, base_url='https://api.example')

        list(forge.iter_pull_requests(RepoRef('a', 'b')))

        # 100 per page is the whole reason the corpus fits in an hour of quota.
        self.assertIn('per_page=100', session.requests[0][0])

    def test_sends_the_token(self):
        session = FakeSession([FakeResponse(payload=[], headers={})])
        forge = GitHubForge(token='secret', session=session, base_url='https://api.example')

        list(forge.iter_pull_requests(RepoRef('a', 'b')))

        self.assertEqual(session.requests[0][1]['Authorization'], 'Bearer secret')

    def test_omits_authorization_when_no_token(self):
        session = FakeSession([FakeResponse(payload=[], headers={})])
        forge = GitHubForge(token='', session=session, base_url='https://api.example')

        list(forge.iter_pull_requests(RepoRef('a', 'b')))

        self.assertNotIn('Authorization', session.requests[0][1])

    def test_source_id_matches_the_spec_form(self):
        session = FakeSession([FakeResponse(payload=[self._pr(42)], headers={})])
        forge = GitHubForge(token='t', session=session, base_url='https://api.example')

        pull = next(iter(forge.iter_pull_requests(RepoRef('a', 'b'))))

        self.assertEqual(pull.source_id, 'pr:42')


class TestReviewComments(unittest.TestCase):
    def test_extracts_pull_number_from_url(self):
        session = FakeSession([
            FakeResponse(
                payload=[{
                    'id': 900,
                    'pull_request_url': 'https://api.github.com/repos/a/b/pulls/77',
                    'user': {'login': 'reviewer'},
                    'body': 'this needs a comment explaining why',
                    'path': 'src/thing.py',
                    'created_at': '2026-01-01T00:00:00Z',
                    'html_url': 'https://github.com/a/b/pull/77#r900',
                }],
                headers={},
            )
        ])
        forge = GitHubForge(token='t', session=session, base_url='https://api.example')

        comment = next(iter(forge.iter_review_comments(RepoRef('a', 'b'))))

        self.assertEqual(comment.pull_number, 77)
        self.assertEqual(comment.source_id, 'review:900')
        self.assertEqual(comment.path, 'src/thing.py')

    def test_uses_the_repo_wide_endpoint(self):
        session = FakeSession([FakeResponse(payload=[], headers={})])
        forge = GitHubForge(token='t', session=session, base_url='https://api.example')

        list(forge.iter_review_comments(RepoRef('a', 'b')))

        # No PR number in the path: one sweep, not one request per PR.
        self.assertIn('/repos/a/b/pulls/comments', session.requests[0][0])


class TestErrorHandling(unittest.TestCase):
    def test_exhausted_quota_raises_rate_limited(self):
        session = FakeSession([
            FakeResponse(
                status_code=403,
                headers={'x-ratelimit-remaining': '0', 'x-ratelimit-reset': '1800000000'},
                text='rate limit exceeded',
            )
        ])
        forge = GitHubForge(token='t', session=session, base_url='https://api.example')

        with self.assertRaises(RateLimited) as raised:
            list(forge.iter_pull_requests(RepoRef('a', 'b')))

        self.assertEqual(raised.exception.reset_at, 1800000000.0)

    def test_secondary_limit_with_retry_after_raises_rate_limited(self):
        session = FakeSession([
            FakeResponse(status_code=429, headers={'retry-after': '60'}, text='slow down')
        ])
        forge = GitHubForge(token='t', session=session, base_url='https://api.example')

        with self.assertRaises(RateLimited):
            list(forge.iter_pull_requests(RepoRef('a', 'b')))

    def test_missing_repo_raises_forge_error(self):
        session = FakeSession([FakeResponse(status_code=404, text='Not Found')])
        forge = GitHubForge(token='t', session=session, base_url='https://api.example')

        with self.assertRaises(ForgeError):
            list(forge.iter_pull_requests(RepoRef('a', 'b')))

    def test_server_error_is_retried_then_surfaced(self):
        slept: list[float] = []
        session = FakeSession([
            FakeResponse(status_code=502, text='bad gateway'),
            FakeResponse(status_code=502, text='bad gateway'),
            FakeResponse(status_code=502, text='bad gateway'),
        ])
        forge = GitHubForge(
            token='t', session=session, base_url='https://api.example',
            sleep=slept.append,
        )

        with self.assertRaises(ForgeError):
            list(forge.iter_pull_requests(RepoRef('a', 'b')))

        self.assertEqual(len(session.requests), 3)
        # Backoff between attempts, and no pointless wait after the last one.
        self.assertEqual(slept, [1, 2])

    def test_server_error_then_success(self):
        session = FakeSession([
            FakeResponse(status_code=503, text='unavailable'),
            FakeResponse(payload=[], headers={}),
        ])
        forge = GitHubForge(
            token='t', session=session, base_url='https://api.example',
            sleep=lambda _seconds: None,
        )

        self.assertEqual(list(forge.iter_pull_requests(RepoRef('a', 'b'))), [])


class TestDumpToDisk(unittest.TestCase):
    def _forge_with(self, pulls, comments):
        session = FakeSession([
            FakeResponse(payload=pulls, headers={}),
            FakeResponse(payload=comments, headers={}),
        ])
        return GitHubForge(
            token='t', session=session, base_url='https://api.example'
        )

    def test_writes_two_jsonl_files(self):
        import json
        import tempfile
        from pathlib import Path

        from repolens.forge import dump_repo_text

        forge = self._forge_with(
            pulls=[{
                'number': 7, 'title': 'T', 'body': 'why we did it',
                'user': {'login': 'a'}, 'state': 'closed',
                'merged_at': None, 'merge_commit_sha': None, 'html_url': 'u',
            }],
            comments=[{
                'id': 3, 'pull_request_url': 'https://x/pulls/7',
                'user': {'login': 'r'}, 'body': 'needs a comment',
                'path': 'a.py', 'created_at': 'now', 'html_url': 'u',
            }],
        )

        with tempfile.TemporaryDirectory() as work_dir:
            result = dump_repo_text(RepoRef('a', 'b'), forge, work_dir)

            self.assertEqual(result.pull_requests, 1)
            self.assertEqual(result.review_comments, 1)
            self.assertEqual(result.requests_made, 2)

            pulls_path = Path(work_dir) / 'pulls.jsonl'
            record = json.loads(pulls_path.read_text().splitlines()[0])
            self.assertEqual(record['body'], 'why we did it')
            self.assertEqual(record['source_id'], 'pr:7')

            # No half-written files left behind.
            leftovers = list(Path(work_dir).glob('*.partial'))
            self.assertEqual(leftovers, [])

    def test_request_count_reflects_bulk_paging(self):
        # Two pages of pulls plus one of comments: three requests for
        # everything, not one per pull request.
        session = FakeSession([
            FakeResponse(payload=[], headers={'link': '<https://api.example/p2>; rel="next"'}),
            FakeResponse(payload=[], headers={}),
            FakeResponse(payload=[], headers={}),
        ])
        forge = GitHubForge(token='t', session=session, base_url='https://api.example')

        import tempfile

        from repolens.forge import dump_repo_text

        with tempfile.TemporaryDirectory() as work_dir:
            result = dump_repo_text(RepoRef('a', 'b'), forge, work_dir)

        self.assertEqual(result.requests_made, 3)
        self.assertEqual(forge.request_count, 3)


if __name__ == '__main__':
    unittest.main()
