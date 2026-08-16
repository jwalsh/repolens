"""Forge client — PR bodies and review threads.

RFC 028 §21 option 1. R1 kills the claim tier if median claim yield falls
below 4%, and §14.3 estimates that yield roughly doubles when PR text is
available. Measuring R1 on commit bodies alone would therefore be biased
toward deleting M2 on evidence that understates it by half. This module is
what makes the honest measurement possible.

*Bulk endpoints, not per-commit lookups.* The obvious shape -- resolve each
merge commit to a PR, fetch that PR -- costs one request per PR and would put
a 20-repository corpus far outside an hour of API budget. GitHub's list
endpoints return full bodies 100 at a time, and review comments have a
repo-wide endpoint that never needs a PR number at all. The corpus becomes
low hundreds of requests instead of tens of thousands, which is the difference
between the R1 study being routine and being an event.

*Conservative PR resolution.* ``pr_number_from_commit`` refuses to guess. A
bare ``#123`` in a commit body is an issue reference far more often than it is
the pull request that merged the change, and under spec invariant I1 a wrong
association means an evidence span pointing at prose the author never wrote
about this commit. Returning None is cheap; a plausible wrong answer is not.
"""
from __future__ import annotations

import json
import os
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator, Protocol
from urllib.parse import urlparse

GITHUB_API = 'https://api.github.com'
PAGE_SIZE = 100
MAX_RETRIES = 3
USER_AGENT = 'repolens-provenance-lens'


class ForgeError(RuntimeError):
    """A forge request could not be completed."""


class RateLimited(ForgeError):
    """The forge refused the request for quota reasons."""

    def __init__(self, message: str, reset_at: float | None = None) -> None:
        super().__init__(message)
        self.reset_at = reset_at


@dataclass(frozen=True)
class RepoRef:
    owner: str
    name: str

    @property
    def slug(self) -> str:
        return f'{self.owner}/{self.name}'


@dataclass(frozen=True)
class PullRequest:
    number: int
    title: str
    body: str
    author: str
    state: str
    merged_at: str | None
    merge_commit_sha: str | None
    url: str

    @property
    def source_id(self) -> str:
        """Matches the spec's evidence-span source_id form."""
        return f'pr:{self.number}'


@dataclass(frozen=True)
class ReviewComment:
    comment_id: int
    pull_number: int
    author: str
    body: str
    path: str | None
    created_at: str
    url: str

    @property
    def source_id(self) -> str:
        return f'review:{self.comment_id}'


@dataclass(frozen=True)
class RateLimit:
    limit: int
    remaining: int
    reset_at: float


class Response(Protocol):
    status_code: int
    headers: Any

    def json(self) -> Any: ...

    @property
    def text(self) -> str: ...


class Session(Protocol):
    def get(self, url: str, headers: dict[str, str], timeout: float) -> Response: ...


# --------------------------------------------------------------- pure parts

_SSH_URL = re.compile(r'^git@([^:]+):(?P<owner>[^/]+)/(?P<name>.+?)(?:\.git)?$')

# `Merge pull request #123 from fork/branch` -- the classic merge commit.
_MERGE_PR = re.compile(r'^Merge pull request #(\d+)\b')
# `Some change (#123)` -- squash and rebase merges put it in the subject tail.
_SQUASH_PR = re.compile(r'\(#(\d+)\)\s*$')
# GitLab writes `See merge request group/project!123` into the body.
_GITLAB_MR = re.compile(r'^See merge request\s+\S*!(\d+)', re.MULTILINE)


def parse_repo_ref(repo_url: str) -> RepoRef | None:
    """Extract owner and repository name from a clone URL.

    Returns None rather than guessing for anything that is not recognisably a
    forge URL -- a local fixture path, for instance.
    """
    if not repo_url:
        return None

    ssh_match = _SSH_URL.match(repo_url.strip())
    if ssh_match:
        return RepoRef(ssh_match.group('owner'), ssh_match.group('name'))

    parsed = urlparse(repo_url.strip())
    if parsed.scheme not in ('http', 'https') or not parsed.netloc:
        return None

    parts = [segment for segment in parsed.path.split('/') if segment]
    if len(parts) < 2:
        return None

    owner, name = parts[0], parts[1]
    if name.endswith('.git'):
        name = name[: -len('.git')]
    return RepoRef(owner, name) if owner and name else None


def pr_number_from_commit(subject: str, body: str = '') -> int | None:
    """Resolve a merge or squash commit to its pull request number.

    Deliberately narrow. Only three forms are accepted, all of which the forge
    itself writes:

      Merge pull request #123 from fork/branch     merge commit
      Fix the thing (#123)                         squash / rebase merge
      See merge request group/project!123          GitLab

    A bare ``#123`` anywhere else is not accepted. ``Fixes #123`` and
    ``Closes #45`` reference issues, and attaching an issue's prose to a
    commit as if it were the pull request's would put a false evidence span
    behind a claim.
    """
    subject = (subject or '').strip()

    merge_match = _MERGE_PR.match(subject)
    if merge_match:
        return int(merge_match.group(1))

    squash_match = _SQUASH_PR.search(subject)
    if squash_match:
        return int(squash_match.group(1))

    gitlab_match = _GITLAB_MR.search(body or '')
    if gitlab_match:
        return int(gitlab_match.group(1))

    return None


def parse_link_header(link: str | None) -> dict[str, str]:
    """RFC 5988 Link header -> {rel: url}. GitHub paginates with this."""
    if not link:
        return {}

    links: dict[str, str] = {}
    for section in link.split(','):
        parts = section.split(';')
        if len(parts) < 2:
            continue
        url = parts[0].strip().lstrip('<').rstrip('>')
        for parameter in parts[1:]:
            key, _, value = parameter.strip().partition('=')
            if key.strip() == 'rel':
                links[value.strip().strip('"')] = url
    return links


# ------------------------------------------------------------------- client


class GitHubForge:
    """Read-only GitHub client. Bulk listing only; no per-PR fetches."""

    def __init__(
        self,
        token: str | None = None,
        session: Session | None = None,
        base_url: str = GITHUB_API,
        sleep: Any = time.sleep,
    ) -> None:
        self.base_url = base_url.rstrip('/')
        # Request budgeting is the point of the bulk design; make it visible.
        self._request_count = 0
        self.token = token if token is not None else os.environ.get('GITHUB_TOKEN')
        self._sleep = sleep

        if session is None:
            import requests

            session = requests.Session()
        self._session = session

    @property
    def request_count(self) -> int:
        """Requests issued so far, retries included."""
        return self._request_count

    # ------------------------------------------------------------ transport

    def _headers(self) -> dict[str, str]:
        headers = {
            'Accept': 'application/vnd.github+json',
            'X-GitHub-Api-Version': '2022-11-28',
            'User-Agent': USER_AGENT,
        }
        if self.token:
            headers['Authorization'] = f'Bearer {self.token}'
        return headers

    def _get(self, url: str) -> Response:
        last_error: str = ''
        for attempt in range(MAX_RETRIES):
            response = self._session.get(
                url, headers=self._headers(), timeout=30.0
            )
            self._request_count += 1
            status = response.status_code

            if status == 200:
                return response

            if status in (403, 429):
                remaining = response.headers.get('x-ratelimit-remaining')
                retry_after = response.headers.get('retry-after')
                if remaining == '0' or retry_after:
                    reset = response.headers.get('x-ratelimit-reset')
                    raise RateLimited(
                        f'Rate limited on {url}'
                        + (f'; retry after {retry_after}s' if retry_after else ''),
                        reset_at=float(reset) if reset else None,
                    )

            if status == 404:
                raise ForgeError(f'Not found: {url}')

            if status < 500 and status not in (403, 429):
                raise ForgeError(f'{status} from {url}: {response.text[:200]}')

            last_error = f'{status} from {url}'
            # Exponential backoff on 5xx and on 403s that are not quota. No
            # sleep after the final attempt -- there is nothing left to wait
            # for, and a backfill of 20 repositories pays that wait per repo.
            if attempt < MAX_RETRIES - 1:
                self._sleep(2**attempt)

        raise ForgeError(f'Giving up after {MAX_RETRIES} attempts: {last_error}')

    def _paginate(self, path: str, **params: str | int) -> Iterator[dict[str, Any]]:
        query = '&'.join(f'{key}={value}' for key, value in params.items())
        url = f'{self.base_url}{path}?{query}' if query else f'{self.base_url}{path}'

        while url:
            response = self._get(url)
            payload = response.json()
            if not isinstance(payload, list):
                raise ForgeError(f'Expected a list from {url}')
            yield from payload
            url = parse_link_header(response.headers.get('link')).get('next', '')

    # --------------------------------------------------------------- reads

    def iter_pull_requests(
        self, ref: RepoRef, state: str = 'all'
    ) -> Iterator[PullRequest]:
        """Every pull request, newest first, bodies included.

        One request per 100 pull requests. The per-PR endpoint returns nothing
        this one does not, and costs 100x.
        """
        for item in self._paginate(
            f'/repos/{ref.slug}/pulls',
            state=state,
            per_page=PAGE_SIZE,
            sort='created',
            direction='desc',
        ):
            yield PullRequest(
                number=item['number'],
                title=item.get('title') or '',
                body=item.get('body') or '',
                author=(item.get('user') or {}).get('login') or '',
                state=item.get('state') or '',
                merged_at=item.get('merged_at'),
                merge_commit_sha=item.get('merge_commit_sha'),
                url=item.get('html_url') or '',
            )

    def iter_review_comments(self, ref: RepoRef) -> Iterator[ReviewComment]:
        """Every review comment in the repository.

        Repo-wide, so it needs no PR numbers and costs one request per 100
        comments regardless of how they are distributed across pull requests.
        """
        for item in self._paginate(
            f'/repos/{ref.slug}/pulls/comments',
            per_page=PAGE_SIZE,
            sort='created',
            direction='desc',
        ):
            yield ReviewComment(
                comment_id=item['id'],
                pull_number=_pull_number_from_url(item.get('pull_request_url') or ''),
                author=(item.get('user') or {}).get('login') or '',
                body=item.get('body') or '',
                path=item.get('path'),
                created_at=item.get('created_at') or '',
                url=item.get('html_url') or '',
            )

    def rate_limit(self) -> RateLimit:
        response = self._get(f'{self.base_url}/rate_limit')
        core = response.json()['resources']['core']
        return RateLimit(
            limit=core['limit'],
            remaining=core['remaining'],
            reset_at=float(core['reset']),
        )


def _pull_number_from_url(pull_request_url: str) -> int:
    """`.../repos/o/n/pulls/123` -> 123. Zero when absent."""
    tail = pull_request_url.rstrip('/').rsplit('/', 1)[-1]
    return int(tail) if tail.isdigit() else 0


# ---------------------------------------------------------------- to disk


@dataclass(frozen=True)
class DumpResult:
    slug: str
    pull_requests: int
    review_comments: int
    requests_made: int


def dump_repo_text(
    ref: RepoRef,
    forge: GitHubForge,
    out_dir: str | os.PathLike[str],
) -> DumpResult:
    """Materialize a repository's prose to JSONL.

    Two files, one object per line: ``pulls.jsonl`` and
    ``review_comments.jsonl``. Written whole then renamed, so an interrupted
    dump leaves no half-file for the R1 study to read as complete.

    Text only. No diffs -- spec invariant I2 forbids inferring intent from a
    hunk, and a file of diffs sitting next to the prose is an invitation.
    """
    directory = Path(out_dir)
    directory.mkdir(parents=True, exist_ok=True)

    before = forge.request_count

    pull_count = _write_jsonl(
        directory / 'pulls.jsonl',
        (
            {
                'number': pull.number,
                'title': pull.title,
                'body': pull.body,
                'author': pull.author,
                'state': pull.state,
                'merged_at': pull.merged_at,
                'merge_commit_sha': pull.merge_commit_sha,
                'url': pull.url,
                'source_id': pull.source_id,
            }
            for pull in forge.iter_pull_requests(ref)
        ),
    )

    comment_count = _write_jsonl(
        directory / 'review_comments.jsonl',
        (
            {
                'comment_id': comment.comment_id,
                'pull_number': comment.pull_number,
                'author': comment.author,
                'body': comment.body,
                'path': comment.path,
                'created_at': comment.created_at,
                'url': comment.url,
                'source_id': comment.source_id,
            }
            for comment in forge.iter_review_comments(ref)
        ),
    )

    return DumpResult(
        slug=ref.slug,
        pull_requests=pull_count,
        review_comments=comment_count,
        requests_made=forge.request_count - before,
    )


def _write_jsonl(path: Path, records: Any) -> int:
    temporary = path.with_suffix(path.suffix + '.partial')
    count = 0
    with temporary.open('w') as handle:
        for record in records:
            handle.write(json.dumps(record, sort_keys=True) + '\n')
            count += 1
    temporary.replace(path)
    return count
