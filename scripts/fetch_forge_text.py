#!/usr/bin/env python
"""Materialize forge prose for a corpus of repositories.

RFC 028 §21. Writes ``pulls.jsonl`` and ``review_comments.jsonl`` per
repository, which is what the R1 claim-yield study reads. Text only -- no
diffs, per spec invariant I2.

Checkpointed by repository slug, so hitting the hourly rate limit is an
interruption rather than a loss: rerun after the reset and it picks up where
it stopped.

    export GITHUB_TOKEN=...
    python scripts/fetch_forge_text.py --corpus experiments/001-substrate/corpus.txt
    python scripts/fetch_forge_text.py --limit 2 --out /tmp/forge-smoke

Unauthenticated access is 60 requests per hour, which is not enough to
materialize even one mid-sized repository. The script refuses to start
without a token unless you insist with --no-token.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from repolens.forge import (  # noqa: E402
    GitHubForge,
    RateLimited,
    RepoRef,
    dump_repo_text,
    parse_repo_ref,
)
from repolens.jobs import CheckpointStore, JobAbort, run_job  # noqa: E402

JOB_ID = 'forge-text'


def read_corpus(path: Path, limit: int | None = None) -> list[str]:
    urls = [
        line.strip()
        for line in path.read_text().splitlines()
        if line.strip() and not line.strip().startswith('#')
    ]
    return urls[:limit] if limit else urls


def resolve(urls: list[str]) -> tuple[dict[str, RepoRef], list[str]]:
    """Split a corpus into forge-hosted repositories and everything else."""
    refs: dict[str, RepoRef] = {}
    skipped: list[str] = []
    for url in urls:
        ref = parse_repo_ref(url)
        if ref is None:
            skipped.append(url)
        else:
            refs[ref.slug] = ref
    return refs, skipped


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        '--corpus', type=Path,
        default=Path('experiments/001-substrate/corpus.txt'),
    )
    parser.add_argument('--limit', type=int, default=None)
    parser.add_argument('--out', type=Path, default=Path('.forge'))
    parser.add_argument(
        '--no-token', action='store_true',
        help='Proceed without GITHUB_TOKEN. 60 requests/hour; you will stop.',
    )
    args = parser.parse_args(argv)

    token = os.environ.get('GITHUB_TOKEN')
    if not token and not args.no_token:
        parser.error(
            'GITHUB_TOKEN is not set. Unauthenticated access is 60 requests '
            'per hour, which will not materialize one repository. Set a token '
            'or pass --no-token to try anyway.'
        )

    refs, skipped = resolve(read_corpus(args.corpus, args.limit))
    for url in skipped:
        print(f'skip  {url} (not a forge URL)', file=sys.stderr)
    if not refs:
        parser.error(f'no forge-hosted repositories in {args.corpus}')

    forge = GitHubForge(token=token)
    args.out.mkdir(parents=True, exist_ok=True)
    results: dict[str, dict[str, int]] = {}

    def fetch(slug: str) -> None:
        ref = refs[slug]
        target = args.out / slug.replace('/', '__')
        try:
            result = dump_repo_text(ref, forge, target)
        except RateLimited as limited:
            # An exhausted quota will fail every remaining repository too.
            # JobAbort stops the run with checkpoints intact instead of
            # marking the whole corpus failed.
            raise JobAbort(str(limited), cause=limited) from limited
        results[slug] = {
            'pull_requests': result.pull_requests,
            'review_comments': result.review_comments,
            'requests': result.requests_made,
        }
        print(
            f'ok    {slug}: {result.pull_requests} PRs, '
            f'{result.review_comments} review comments, '
            f'{result.requests_made} requests'
        )

    started = time.monotonic()
    with CheckpointStore(args.out / 'checkpoints.sqlite') as checkpoints:
        try:
            outcome = run_job(JOB_ID, sorted(refs), fetch, checkpoints)
        except JobAbort as abort:
            # Checkpoints hold. Report when the quota comes back and stop.
            reset = getattr(abort.cause, 'reset_at', None)
            when = (
                time.strftime('%H:%M:%S', time.localtime(reset)) if reset else 'unknown'
            )
            print(
                f'\nrate limited after {forge.request_count} requests; '
                f'quota resets at {when}. Progress is checkpointed -- rerun '
                f'this command to continue.',
                file=sys.stderr,
            )
            return 2

    summary = {
        'repositories': len(refs),
        'completed': len(checkpoints_completed(args.out)),
        'skipped_non_forge': len(skipped),
        'requests_total': forge.request_count,
        'seconds': round(time.monotonic() - started, 1),
        'failed': outcome.failed,
        'per_repo': results,
    }
    (args.out / 'summary.json').write_text(json.dumps(summary, indent=2, sort_keys=True))

    print(
        f'\n{summary["completed"]}/{len(refs)} repositories, '
        f'{forge.request_count} requests, {summary["seconds"]}s'
    )
    if outcome.failed:
        for slug, error in outcome.failed.items():
            print(f'fail  {slug}: {error}', file=sys.stderr)
        return 1
    return 0


def checkpoints_completed(out: Path) -> set[str]:
    with CheckpointStore(out / 'checkpoints.sqlite') as store:
        return store.completed(JOB_ID)


if __name__ == '__main__':
    raise SystemExit(main())
