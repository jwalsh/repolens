"""Vendored and generated file classification.

RFC 028 §28. The spec's §5 drops machine-authored paths with an inline
``GENERATED`` regex before counting co-change, and that regex carries more
weight than a regex can. R2 refutes co-change if maintainers judge top-lift
neighbours unrelated more often than related, and a weak exclusion filter is
the most likely way to fail R2 for a reason that has nothing to do with
whether co-change measures coupling.

Three decisions, each with a reason it is not the obvious one.

*This does not read ``.gitignore``.* A tracked file is by definition one that
was not ignored, so ``.gitignore`` says almost nothing about the files
co-change counts -- it catches only force-added artifacts. The signal that
applies to tracked files is ``.gitattributes``: ``linguist-vendored`` and
``linguist-generated`` mark machine-authored files that are deliberately in
the repository.

*Attributes are resolved at a revision, not at HEAD.* Ignore and attribute
rules are versioned. Filtering a ten-year co-change window through today's
rules is an anachronism, and it is not hypothetical -- see
``tests/test_ignores.py::test_the_same_path_classifies_differently_across_revisions``,
where one file is generated at one commit and unspecified at the next.
``git check-attr --source=<rev>`` resolves against any revision and works in
a bare mirror, which is the only reason this is affordable.

*git does the resolution, not us.* We already require the binary, and it is
ground truth by construction. Reimplementing hierarchical ``.gitattributes``
precedence is how tools get this subtly wrong; see the module docstring in
``tests/test_ignores.py`` for the measured comparison. ``pathspec`` supplies
gitignore *pattern* semantics for the heuristic layer, where there is no
authored answer to defer to.

Authored beats inferred, the same ordering the spec applies to trailers over
model output in §6: an explicit ``linguist-generated`` attribute wins over
any path heuristic, and the heuristic never overrides an attribute that says
a file is human-authored.
"""
from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

import pathspec

from repolens.gitcheck import require_git

ATTR_VENDORED = 'linguist-vendored'
ATTR_GENERATED = 'linguist-generated'

# Heuristics, in gitignore syntax so callers extend them in the syntax they
# already know. Derived from github/linguist's vendor.yml and generated.rb,
# which is the closest thing to a maintained public answer for "is this file
# machine-authored". Kept short on purpose: every pattern here is a guess that
# can silently drop real source, and R2 is measured against the result.
VENDORED_PATTERNS: tuple[str, ...] = (
    'vendor/',
    '**/vendor/',
    'third_party/',
    '**/third_party/',
    '**/3rdparty/',
    '**/node_modules/',
    '**/bower_components/',
    '**/Godeps/',
    '**/.yarn/releases/',
    '**/*.min.js',
    '**/*.min.css',
)

GENERATED_PATTERNS: tuple[str, ...] = (
    # Lockfiles: authored by a resolver, not by a person.
    '**/package-lock.json',
    '**/yarn.lock',
    '**/pnpm-lock.yaml',
    '**/poetry.lock',
    '**/Pipfile.lock',
    '**/Cargo.lock',
    '**/composer.lock',
    '**/Gemfile.lock',
    '**/go.sum',
    '**/mix.lock',
    '**/flake.lock',
    '**/gradle.lockfile',
    # Protocol and IDL output.
    '**/*_pb2.py',
    '**/*_pb2_grpc.py',
    '**/*.pb.go',
    '**/*_pb.js',
    '**/*.pb.cc',
    '**/*.pb.h',
    # Rails commits its schema by convention -- `rails db:migrate` rewrites it
    # from the migrations, and it is meant to be checked in. Earned by audit:
    # rubygems.org tracks db/schema.rb and 248 of its 12,561 commits touch it.
    # See experiments/002-heuristic-coverage.
    '**/db/schema.rb',
    '**/db/structure.sql',
    # Conventional generator markers.
    '**/*.generated.*',
    '**/*_generated.go',
    '**/*.g.dart',
    '**/*.designer.cs',
    '**/*.map',
    # Autotools.
    '**/configure',
    '**/config.guess',
    '**/config.sub',
    '**/aclocal.m4',
    '**/Makefile.in',
)


class IgnoreError(RuntimeError):
    """Classification could not be completed."""


@dataclass(frozen=True)
class Classification:
    path: str
    vendored: bool = False
    generated: bool = False
    source: str = 'none'  # 'gitattributes' | 'heuristic' | 'extra' | 'none'
    rule: str = ''

    @property
    def excluded(self) -> bool:
        return self.vendored or self.generated


@dataclass(frozen=True)
class ClassificationStats:
    revision: str
    total: int
    excluded: int
    attributes_available: bool
    by_source: dict[str, int] = field(default_factory=dict)

    @property
    def excluded_fraction(self) -> float:
        return self.excluded / self.total if self.total else 0.0


class IgnoreResolver:
    """Classifies tracked paths as vendored or generated at a revision."""

    def __init__(
        self,
        clone_path: str | os.PathLike[str],
        *,
        extra_vendored: tuple[str, ...] = (),
        extra_generated: tuple[str, ...] = (),
        use_attributes: bool = True,
    ) -> None:
        self.clone_path = Path(clone_path)

        if use_attributes:
            # Raise rather than quietly fall back to heuristics. Dropping the
            # authored layer changes the answers without changing the shape of
            # the result, which is indistinguishable from working. Ask for
            # use_attributes=False to accept heuristics only.
            require_git()
        self.use_attributes = use_attributes

        self._vendored = _spec(VENDORED_PATTERNS)
        self._generated = _spec(GENERATED_PATTERNS)
        self._extra_vendored = _spec(extra_vendored)
        self._extra_generated = _spec(extra_generated)

        # Correct-by-revision, not by attributes blob. Two commits can share a
        # root .gitattributes and still differ in a nested one, and a cache
        # that gets that wrong is worse than no cache.
        self._attr_cache: dict[tuple[str, str], tuple[bool, bool]] = {}

    @property
    def attributes_available(self) -> bool:
        return self.use_attributes

    # ---------------------------------------------------------------- api

    def classify(
        self, paths: list[str], revision: str = 'HEAD'
    ) -> dict[str, Classification]:
        """Classify every path. One git process per call, not per path."""
        if not paths:
            return {}

        attributes = (
            self._attributes(paths, revision) if self.use_attributes else {}
        )

        results: dict[str, Classification] = {}
        for path in paths:
            vendored, generated = attributes.get(path, (False, False))
            if vendored or generated:
                # Authored. Wins over every heuristic below.
                results[path] = Classification(
                    path=path,
                    vendored=vendored,
                    generated=generated,
                    source='gitattributes',
                    rule=ATTR_VENDORED if vendored else ATTR_GENERATED,
                )
                continue

            results[path] = self._by_pattern(path)
        return results

    def filter(self, paths: list[str], revision: str = 'HEAD') -> list[str]:
        """Paths that survive classification, order preserved."""
        classified = self.classify(paths, revision)
        return [path for path in paths if not classified[path].excluded]

    def stats(
        self, paths: list[str], revision: str = 'HEAD'
    ) -> ClassificationStats:
        classified = self.classify(paths, revision)
        by_source: dict[str, int] = {}
        excluded = 0
        for result in classified.values():
            if result.excluded:
                excluded += 1
                by_source[result.source] = by_source.get(result.source, 0) + 1
        return ClassificationStats(
            revision=revision,
            total=len(paths),
            excluded=excluded,
            attributes_available=self.use_attributes,
            by_source=by_source,
        )

    # ----------------------------------------------------------- internals

    def _by_pattern(self, path: str) -> Classification:
        if self._extra_generated.match_file(path):
            return Classification(path, generated=True, source='extra', rule='generated')
        if self._extra_vendored.match_file(path):
            return Classification(path, vendored=True, source='extra', rule='vendored')
        if self._generated.match_file(path):
            return Classification(
                path, generated=True, source='heuristic', rule='generated'
            )
        if self._vendored.match_file(path):
            return Classification(
                path, vendored=True, source='heuristic', rule='vendored'
            )
        return Classification(path)

    def _attributes(
        self, paths: list[str], revision: str
    ) -> dict[str, tuple[bool, bool]]:
        uncached = [path for path in paths if (revision, path) not in self._attr_cache]
        if uncached:
            self._attr_cache.update(
                {
                    (revision, path): value
                    for path, value in _check_attr(
                        self.clone_path, revision, uncached
                    ).items()
                }
            )
        return {path: self._attr_cache[(revision, path)] for path in paths}


def _spec(patterns: tuple[str, ...]) -> pathspec.PathSpec:
    # 'gitignore', not the older 'gitwildmatch', which pathspec 1.1 deprecates.
    return pathspec.PathSpec.from_lines('gitignore', patterns)


def _check_attr(
    clone_path: Path, revision: str, paths: list[str]
) -> dict[str, tuple[bool, bool]]:
    """Batched `git check-attr`. Returns {path: (vendored, generated)}.

    NUL-delimited on both ends: paths contain spaces, quotes and newlines, and
    the line-oriented form mangles them.
    """
    completed = subprocess.run(
        [
            'git', '--git-dir', str(clone_path), 'check-attr',
            f'--source={revision}', '--stdin', '-z',
            ATTR_VENDORED, ATTR_GENERATED,
        ],
        input='\0'.join(paths) + '\0',
        capture_output=True,
        text=True,
        env={**os.environ, 'GIT_TERMINAL_PROMPT': '0'},
    )
    if completed.returncode != 0:
        raise IgnoreError(
            f'git check-attr failed at {revision}: {completed.stderr.strip()}'
        )

    # Output is a flat NUL-separated stream of (path, attribute, value).
    fields = completed.stdout.split('\0')
    result: dict[str, tuple[bool, bool]] = {path: (False, False) for path in paths}
    for index in range(0, len(fields) - 2, 3):
        path, attribute, value = fields[index], fields[index + 1], fields[index + 2]
        if path not in result:
            continue
        vendored, generated = result[path]
        if attribute == ATTR_VENDORED:
            vendored = _is_set(value)
        elif attribute == ATTR_GENERATED:
            generated = _is_set(value)
        result[path] = (vendored, generated)
    return result


# `foo` reports as "set"; `foo=true` reports as the literal "true". Both mean
# the same thing to linguist, and the `=true` spelling is not exotic --
# kubernetes/kubernetes writes every one of its linguist-generated rules that
# way. Matching only "set" silently drops the authored layer for those repos,
# which is the failure this whole module exists to avoid.
_TRUTHY_ATTR = frozenset({'set', 'true'})


def _is_set(value: str) -> bool:
    """Whether a git attribute value means the attribute is on.

    Everything else -- "unset", "false", "unspecified", or any other custom
    value -- is off. `-linguist-vendored` and `linguist-vendored=false` are
    both an author saying the file is theirs, and are honoured as such.
    """
    return value.strip().lower() in _TRUTHY_ATTR
