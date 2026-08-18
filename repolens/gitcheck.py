"""Minimum git version, enforced rather than detected.

RepoLens is a git-analysis tool that shells out to git for everything:
``clone --mirror``, ``ls-tree -z``, ``blame --line-porcelain``, and
``check-attr --source``. The last of those landed in git 2.40 and is what
lets ``repolens.ignores`` resolve ``.gitattributes`` at an arbitrary
revision instead of assuming HEAD.

This module exists because the alternative -- degrade quietly on old git --
is the failure mode this repository has already been bitten by twice. A
suite that skips its coverage and reports OK, and an ignore resolver that
drops its authored layer and returns heuristics, both look like success. A
tool whose answers silently get worse on an old dependency is worse than one
that refuses to start.

So: refuse to start. Callers who genuinely want the degraded behaviour ask
for it by name (``IgnoreResolver(..., use_attributes=False)``).
"""
from __future__ import annotations

import re
import subprocess

# `check-attr --source=<rev>`. Everything else RepoLens uses is far older.
MIN_GIT = (2, 40)

_VERSION = re.compile(r'(\d+)\.(\d+)(?:\.(\d+))?')


class GitTooOld(RuntimeError):
    """The installed git predates something RepoLens requires."""


class GitMissing(RuntimeError):
    """No usable git on PATH."""


def parse_version(output: str) -> tuple[int, int, int] | None:
    """Extract a version tuple from `git --version` output.

    Returns None when the string does not contain a recognisable version,
    which is treated as "too old" everywhere rather than "probably fine" --
    an unparseable version is not evidence of a new git.
    """
    for token in output.split():
        match = _VERSION.fullmatch(token)
        if match:
            major, minor, patch = match.groups()
            return (int(major), int(minor), int(patch or 0))
    return None


def git_version() -> tuple[int, int, int] | None:
    try:
        completed = subprocess.run(
            ['git', '--version'], capture_output=True, text=True, check=True
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    return parse_version(completed.stdout)


def supports_attr_source(version: tuple[int, int, int] | None = None) -> bool:
    """Whether `git check-attr --source` is available."""
    resolved = git_version() if version is None else version
    return resolved is not None and resolved[:2] >= MIN_GIT


def require_git(minimum: tuple[int, int] = MIN_GIT) -> tuple[int, int, int]:
    """Assert a usable git, or raise with something actionable.

    Called at application startup and when constructing an
    ``IgnoreResolver`` that intends to read attributes.
    """
    version = git_version()

    if version is None:
        raise GitMissing(
            'No usable git found on PATH. RepoLens shells out to git for '
            'cloning, history walking, blame and attribute resolution; there '
            'is no fallback.'
        )

    if version[:2] < tuple(minimum):
        found = '.'.join(str(part) for part in version)
        needed = '.'.join(str(part) for part in minimum)
        raise GitTooOld(
            f'git {found} is too old; RepoLens requires {needed} or newer. '
            f'`git check-attr --source=<rev>` arrived in 2.40 and is how '
            f'vendored and generated files are classified at a revision '
            f'rather than at HEAD. Upgrade git, or construct '
            f'IgnoreResolver(use_attributes=False) to accept heuristics only.'
        )

    return version
