"""Persistent clone store.

Substrate for the provenance lens (RFC 028, M-1). The packager previously
cloned into a ``tempfile.TemporaryDirectory`` and destroyed the checkout on
the way out of the request, which makes blame-forward anchor resolution --
one blame per claim-bearing file per HEAD change -- impossible to run at all.

Two design commitments:

*Bare mirrors, not working trees.* The lens reads history and runs blame
against an explicit revision. Both work in a bare repository, so a working
tree is pure cost. ``git --git-dir=mirror.git blame HEAD -- path`` and
``git log --name-status`` were both verified against a bare mirror before
this module was written.

*Deterministic, contained paths.* ``path_for`` is a pure function of the URL
and its result is always a direct child of ``root``. A repository URL is
attacker-controlled input on every endpoint that reaches this module, so
containment is a property test (``tests/test_clones.py``), not a code review
note.
"""
from __future__ import annotations

import hashlib
import os
import re
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

# git's ext:: transport executes an arbitrary command from the URL. There is
# no use for it here and it turns a repository URL into remote code execution.
DANGEROUS_SCHEMES = frozenset({"ext"})

_SLUG_ALLOWED = re.compile(r"[^a-z0-9._-]+")
_SLUG_MAX = 48

# Length of the URL digest appended to every clone directory name. Collisions
# would let one repository's history be served for another, so this carries
# the injectivity guarantee that the slug does not.
_DIGEST_CHARS = 32


class CloneError(RuntimeError):
    """A clone or fetch could not be completed."""


@dataclass(frozen=True)
class CloneStats:
    """What one ``ensure`` call did. Feeds the M-1 feasibility gate."""

    repo_url: str
    path: Path
    head_sha: str
    commit_count: int
    bytes_on_disk: int
    duration_seconds: float
    was_cloned: bool  # False means an existing mirror was fetched
    was_unshallowed: bool


def _slugify(repo_url: str) -> str:
    """Human-readable directory prefix. Never load-bearing for correctness."""
    parsed = urlparse(repo_url)
    tail = (parsed.path or repo_url).rstrip("/")
    tail = tail.rsplit("/", 1)[-1]
    if tail.endswith(".git"):
        tail = tail[: -len(".git")]

    slug = _SLUG_ALLOWED.sub("-", tail.lower()).strip("-._")[:_SLUG_MAX]

    # "", ".", ".." and friends would all escape or collide with the root.
    if not slug or set(slug) <= {"."}:
        return "repo"
    return slug


def _dir_size_bytes(path: Path) -> int:
    total = 0
    for dirpath, _dirnames, filenames in os.walk(path):
        for filename in filenames:
            try:
                total += os.lstat(os.path.join(dirpath, filename)).st_size
            except OSError:
                continue
    return total


@dataclass(frozen=True)
class CloneStore:
    """A directory of bare mirrors, one per repository URL."""

    root: Path

    def __post_init__(self) -> None:
        object.__setattr__(self, "root", Path(self.root))

    # ---------------------------------------------------------------- paths

    def path_for(self, repo_url: str) -> Path:
        """Deterministic mirror path. Always a direct child of ``root``.

        The digest, not the slug, is what makes distinct URLs distinct: the
        slug is lossy by design and two different repositories routinely
        share a basename.
        """
        digest = hashlib.sha256(repo_url.encode("utf-8")).hexdigest()[:_DIGEST_CHARS]
        return self.root / f"{_slugify(repo_url)}-{digest}.git"

    def exists(self, repo_url: str) -> bool:
        return (self.path_for(repo_url) / "HEAD").is_file()

    def list_clones(self) -> list[Path]:
        if not self.root.is_dir():
            return []
        return sorted(p for p in self.root.iterdir() if (p / "HEAD").is_file())

    def disk_usage_bytes(self) -> int:
        return _dir_size_bytes(self.root) if self.root.is_dir() else 0

    # ------------------------------------------------------------ mutation

    def ensure(self, repo_url: str, *, unshallow: bool = True) -> CloneStats:
        """Clone the mirror if absent, fetch it if present.

        Idempotent: calling twice against an unchanged remote leaves the same
        path at the same HEAD.
        """
        _validate_url(repo_url)
        path = self.path_for(repo_url)
        started = time.monotonic()

        if self.exists(repo_url):
            was_cloned = False
            # A mirror's refspec is +refs/*:refs/*, so this refreshes every
            # ref rather than just the default branch.
            self._git("fetch", "--prune", "--quiet", cwd=path)
        else:
            was_cloned = True
            self.root.mkdir(parents=True, exist_ok=True)
            if path.exists():
                shutil.rmtree(path)  # partial clone from an earlier failure
            try:
                self._git(
                    "clone", "--mirror", "--quiet", "--", repo_url, str(path)
                )
            except CloneError:
                if path.exists():
                    shutil.rmtree(path, ignore_errors=True)
                raise

        was_unshallowed = False
        if unshallow and self._is_shallow(path):
            self._git("fetch", "--unshallow", "--quiet", cwd=path)
            was_unshallowed = True

        return CloneStats(
            repo_url=repo_url,
            path=path,
            head_sha=self._head_sha(path),
            commit_count=self._commit_count(path),
            bytes_on_disk=_dir_size_bytes(path),
            duration_seconds=time.monotonic() - started,
            was_cloned=was_cloned,
            was_unshallowed=was_unshallowed,
        )

    def evict(self, repo_url: str) -> bool:
        path = self.path_for(repo_url)
        if not path.is_dir():
            return False
        shutil.rmtree(path)
        return True

    # ------------------------------------------------------------- queries

    def head_sha(self, repo_url: str) -> str:
        path = self.path_for(repo_url)
        if not self.exists(repo_url):
            raise CloneError(f"No mirror for {repo_url!r}; call ensure() first")
        return self._head_sha(path)

    def commit_count(self, repo_url: str) -> int:
        path = self.path_for(repo_url)
        if not self.exists(repo_url):
            raise CloneError(f"No mirror for {repo_url!r}; call ensure() first")
        return self._commit_count(path)

    # ------------------------------------------------------------ internals

    def _is_shallow(self, path: Path) -> bool:
        return self._git("rev-parse", "--is-shallow-repository", cwd=path) == "true"

    def _head_sha(self, path: Path) -> str:
        return self._git("rev-parse", "HEAD", cwd=path)

    def _commit_count(self, path: Path) -> int:
        return int(self._git("rev-list", "--count", "HEAD", cwd=path) or 0)

    @staticmethod
    def _git(*argv: str, cwd: Path | None = None) -> str:
        command = ["git"]
        if cwd is not None:
            command += ["--git-dir", str(cwd)]
        command += list(argv)

        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            # Prompting for credentials in a background job runner hangs the
            # worker forever instead of failing.
            env={**os.environ, "GIT_TERMINAL_PROMPT": "0"},
        )
        if completed.returncode != 0:
            raise CloneError(
                f"git {' '.join(argv)} failed ({completed.returncode}): "
                f"{completed.stderr.strip()}"
            )
        return completed.stdout.strip()


def _validate_url(repo_url: str) -> None:
    """Reject inputs that turn a URL into something other than a URL."""
    if not repo_url or not repo_url.strip():
        raise CloneError("Empty repository URL")

    # `git clone -- <url>` already stops option injection, but a URL that
    # looks like a flag is a bug in the caller either way.
    if repo_url.startswith("-"):
        raise CloneError(f"Repository URL may not start with '-': {repo_url!r}")

    scheme = urlparse(repo_url).scheme.lower()
    if scheme in DANGEROUS_SCHEMES:
        raise CloneError(f"Transport {scheme!r} is not permitted")
