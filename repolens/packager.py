"""Repository packaging, backed by the persistent clone store.

Previously this cloned into a ``tempfile.TemporaryDirectory`` and destroyed
the checkout on the way out, which meant every call paid a full clone and no
later stage could run blame against anything. RFC 028 M-1 replaces that with
``repolens.clones.CloneStore``: bare mirrors that survive the request.

Two behaviour changes fall out of the move, both of them fixes:

*File listing comes from ``git ls-tree``, not ``os.walk``.* The old walk had
no exclusion for ``.git``, so every sample hook, pack index and ref file was
counted as a repository file. ``file_count`` was inflated by git internals and
``file_types`` was full of ``sample`` and ``idx``. A bare mirror has no
working tree to walk, which forced the correct implementation.

*The embedded commit list is capped.* §10 budgets for 50k commits; building
that list in memory and writing it to a single JSON column is the thing that
made packaging a request-cycle timeout. The authoritative total now lives in
``commit_count``, computed with ``git rev-list --count``, and the embedded
list is a bounded sample. Full history belongs in ``pl_commit`` at M0.
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

from repolens.clones import CloneError, CloneStore
from repolens.database import db
from repolens.ignores import IgnoreResolver
from repolens.models import Repository

# How many commits to embed in packaged_data. Not a limit on what is walked --
# `commit_count` is exact -- only on what is denormalised into the JSON blob.
EMBEDDED_COMMIT_LIMIT = 500

# Record separator for the commit format below. Commit subjects contain
# every ASCII printable character sooner or later; a control character does
# not survive `git commit` unmangled, so it is a safe delimiter.
_FIELD_SEP = '\x1f'
_RECORD_SEP = '\x1e'


def _git(clone_path: Path, *argv: str) -> str:
    completed = subprocess.run(
        ['git', '--git-dir', str(clone_path), *argv],
        capture_output=True,
        text=True,
        env={**os.environ, 'GIT_TERMINAL_PROMPT': '0'},
    )
    if completed.returncode != 0:
        raise CloneError(
            f"git {' '.join(argv)} failed: {completed.stderr.strip()}"
        )
    return completed.stdout


def _clone_root() -> Path:
    from flask import current_app

    try:
        configured = current_app.config.get('CLONE_ROOT')
    except RuntimeError:  # no application context, e.g. a worker process
        configured = None
    return Path(configured or os.environ.get('REPOLENS_CLONE_ROOT', '.clones'))


def list_files(clone_path: Path) -> list[dict[str, object]]:
    """Tracked files at HEAD, with sizes. Bare-repo safe."""
    output = _git(clone_path, 'ls-tree', '-r', '--long', '-z', 'HEAD')

    files: list[dict[str, object]] = []
    for entry in output.split('\0'):
        if not entry:
            continue
        # "<mode> <type> <sha> <size>\t<path>"
        metadata, _, path = entry.partition('\t')
        parts = metadata.split()
        if len(parts) < 4 or parts[1] != 'blob':
            continue
        size = parts[3]
        files.append({'path': path, 'size': int(size) if size.isdigit() else 0})
    return files


def list_commits(clone_path: Path, limit: int | None = None) -> list[dict[str, str]]:
    """Newest ``limit`` commits. See EMBEDDED_COMMIT_LIMIT for why bounded.

    Resolved at call time rather than bound as a default argument, so the cap
    is patchable without building a 500-commit fixture to observe it.
    """
    limit = EMBEDDED_COMMIT_LIMIT if limit is None else limit
    output = _git(
        clone_path,
        'log',
        f'--max-count={limit}',
        f'--format=%H{_FIELD_SEP}%an <%ae>{_FIELD_SEP}%aI{_FIELD_SEP}%B{_RECORD_SEP}',
        'HEAD',
    )

    commits: list[dict[str, str]] = []
    for record in output.split(_RECORD_SEP):
        record = record.strip('\n')
        if not record:
            continue
        fields = record.split(_FIELD_SEP)
        if len(fields) < 4:
            continue
        commits.append({
            'hash': fields[0],
            'author': fields[1],
            'date': fields[2],
            'message': fields[3],
        })
    return commits


def list_branches(clone_path: Path) -> list[str]:
    output = _git(clone_path, 'for-each-ref', '--format=%(refname:short)', 'refs/heads')
    return [line.strip() for line in output.splitlines() if line.strip()]


def package_repository(repo_url: str) -> tuple[int | None, str | None]:
    """Materialize the repository and persist a snapshot summary.

    Returns ``(repository_id, error)``; exactly one is None.
    """
    store = CloneStore(root=_clone_root())

    try:
        stats = store.ensure(repo_url)
    except CloneError as error:
        return None, f'Error cloning repository: {error}'

    try:
        files = list_files(stats.path)
        repo_data = {
            'name': stats.path.name.rsplit('-', 1)[0],
            'url': repo_url,
            'head_sha': stats.head_sha,
            'commit_count': stats.commit_count,
            'files': files,
            'commits': list_commits(stats.path),
            'branches': list_branches(stats.path),
        }
    except CloneError as error:
        return None, f'Error reading repository: {error}'

    # How much of this repository is machine-authored. Reported, not filtered:
    # deciding what to drop belongs to the consumer, and M0's co-change is the
    # first one that will care. See repolens/ignores.py and RFC 028 §28.
    resolver = IgnoreResolver(stats.path)
    classification = resolver.stats(
        [entry['path'] for entry in files], revision=stats.head_sha
    )
    repo_data['authorship'] = {
        'total_files': classification.total,
        'excluded_files': classification.excluded,
        'excluded_fraction': round(classification.excluded_fraction, 4),
        'by_source': classification.by_source,
        'attributes_available': classification.attributes_available,
    }

    repo_data['commits_truncated'] = (
        repo_data['commit_count'] > len(repo_data['commits'])
    )

    repository = Repository(
        name=repo_data['name'], url=repo_url, packaged_data=repo_data
    )
    db.session.add(repository)
    db.session.commit()

    return repository.id, None
