#!/usr/bin/env python
"""Audit a repository through the substrate that exists today.

Materializes a bare mirror, lists tracked files at HEAD, and classifies them
as vendored, generated, or authored. Prints what was excluded and *why*, plus
the file shapes that survived, so the heuristics can be judged against a real
repository instead of a fixture.

It also reports SUSPECTS: files matching well-known machine-authored
conventions that RepoLens does not currently exclude. Suspects are printed and
never acted on. The point of this script is to find out where the heuristics
are wrong, which it cannot do if it quietly applies whatever it suspects --
and RFC 028 §28 is explicit that every pattern added is a guess that can
delete real source.

    uv run python scripts/audit_repo.py https://github.com/clojure/clojure.git
    uv run python scripts/audit_repo.py --limit-suspects 5 <url> <url> ...
"""
from __future__ import annotations

import argparse
import os
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from repolens.clones import CloneError, CloneStore  # noqa: E402
from repolens.gitcheck import require_git  # noqa: E402
from repolens.ignores import IgnoreResolver  # noqa: E402
from repolens.packager import list_files  # noqa: E402

# Conventions this classifier does NOT know about, grouped by the ecosystem
# that produces them. Reported as candidates, never excluded. Anything
# promoted out of here belongs in repolens/ignores.py with a test.
# `requires` gates an ecosystem's rules on the repository actually being that
# ecosystem. Guile compiles to `.go`, which collides exactly with Go source --
# ungated, that single rule flagged all 722 Go files in prometheus. A suspect
# list that cries wolf is worse than none, because the whole point is that a
# human reads it.
SUSPECT_RULES: dict[str, dict[str, object]] = {
    'emacs': {
        'requires': ('.el',),
        'rules': (
            ('.elc', 'byte-compiled elisp'),
            ('-autoloads.el', 'generated autoloads'),
            ('-pkg.el', 'generated package descriptor'),
            ('loaddefs.el', 'generated autoloads'),
        ),
    },
    'ruby/rails': {
        'requires': ('.rb',),
        'rules': (
            ('.gemspec', 'sometimes generated'),
            ('db/seeds.rb', 'authored, listed to check we do NOT exclude it'),
        ),
    },
    'clojure': {
        'requires': ('.clj', '.cljs', '.cljc'),
        'rules': (
            ('.cpcache', 'classpath cache'),
            ('pom.xml', 'often generated from deps.edn'),
        ),
    },
    'scheme/guile': {
        'requires': ('.scm',),
        'rules': (
            ('.go', 'Guile object file -- only flagged in Scheme repos'),
            ('config.status', 'autotools output'),
            ('libtool', 'autotools output'),
            ('.info', 'generated from texinfo'),
        ),
    },
    'general': {
        'requires': (),
        'rules': (
            ('.pot', 'extracted translation template'),
            ('.mo', 'compiled translation'),
            ('.snap', 'test snapshot'),
        ),
    },
}


def human_bytes(count: int) -> str:
    value = float(count)
    for unit in ('B', 'KiB', 'MiB', 'GiB'):
        if value < 1024 or unit == 'GiB':
            return f'{value:.1f} {unit}'
        value /= 1024
    return f'{value:.1f} GiB'


def extension_of(path: str) -> str:
    name = path.rsplit('/', 1)[-1]
    if '.' not in name or name.startswith('.') and name.count('.') == 1:
        return f'({name})' if '.' not in name else name
    return '.' + name.rsplit('.', 1)[-1]


def find_suspects(paths: list[str], already_excluded: set[str]) -> dict[str, list[str]]:
    """Files matching a known machine-authored convention we do not exclude."""
    present = {extension_of(path) for path in paths}
    hits: dict[str, list[str]] = {}

    for ecosystem, spec in SUSPECT_RULES.items():
        requires: tuple[str, ...] = spec['requires']  # type: ignore[assignment]
        if requires and not any(extension in present for extension in requires):
            continue

        for marker, why in spec['rules']:  # type: ignore[union-attr]
            matched = [
                path
                for path in paths
                if path not in already_excluded
                and (path.endswith(marker) or f'/{marker}' in path or path == marker)
            ]
            if matched:
                hits.setdefault(f'{ecosystem}: {marker} ({why})', []).extend(matched)
    return hits


def attribute_rules(clone_path: Path, revision: str) -> list[str]:
    """linguist-* rules declared in .gitattributes at this revision.

    Read from the file rather than inferred from what was excluded. A rule can
    be present and match nothing -- prometheus declares one for a file that has
    since been deleted -- and "declared but matching nothing" is a different
    fact from "no rules at all". It is also the same shape as the spec's
    orphaned constraints: an assertion that outlived its subject.
    """
    import subprocess

    try:
        blob = subprocess.run(
            ['git', '--git-dir', str(clone_path), 'show', f'{revision}:.gitattributes'],
            capture_output=True, text=True,
        )
    except OSError:
        return []
    if blob.returncode != 0:
        return []

    return [
        line.strip()
        for line in blob.stdout.splitlines()
        if 'linguist-vendored' in line or 'linguist-generated' in line
    ]


def audit(repo_url: str, store: CloneStore, limit_suspects: int) -> dict[str, object]:
    stats = store.ensure(repo_url)
    files = list_files(stats.path)
    paths = [entry['path'] for entry in files]

    resolver = IgnoreResolver(stats.path)
    classified = resolver.classify(paths, revision=stats.head_sha)

    excluded = {p: c for p, c in classified.items() if c.excluded}
    kept = [p for p in paths if p not in excluded]

    declared = attribute_rules(stats.path, stats.head_sha)
    matched_by_attributes = sum(
        1 for c in classified.values() if c.source == 'gitattributes'
    )
    has_attributes = bool(declared)
    by_source = Counter(c.source for c in excluded.values())
    by_kind = Counter(
        'vendored' if c.vendored else 'generated' for c in excluded.values()
    )

    print(f'\n{"=" * 72}')
    print(f'{repo_url}')
    print('=' * 72)
    print(f'  head           {stats.head_sha[:12]}')
    print(f'  commits        {stats.commit_count:,}')
    print(f'  tracked files  {len(paths):,}')
    print(f'  mirror size    {human_bytes(stats.bytes_on_disk)}')
    print(f'  clone time     {stats.duration_seconds:.1f}s')

    fraction = len(excluded) / len(paths) if paths else 0.0
    print(f'\n  EXCLUDED       {len(excluded):,} / {len(paths):,}  ({fraction:.1%})')
    for kind, count in by_kind.most_common():
        print(f'    {kind:<14} {count:,}')
    print('  by source')
    for source, count in by_source.most_common():
        print(f'    {source:<14} {count:,}')
    if not declared:
        print('    (no linguist-* rules in .gitattributes -- heuristics only)')
    else:
        print(f'\n  AUTHORED LAYER   {len(declared)} linguist-* rule(s) declared, '
              f'matching {matched_by_attributes} tracked file(s)')
        for rule in declared[:5]:
            print(f'    {rule}')
        if matched_by_attributes == 0:
            # Same shape as the spec's orphaned constraints: an assertion that
            # outlived its subject. Worth surfacing, not worth "fixing".
            print('    ^ declared but matching nothing: the targets are gone')

    if excluded:
        print('\n  sample exclusions')
        for path in list(excluded)[:8]:
            entry = excluded[path]
            print(f'    {entry.source:<14} {path}')

    print('\n  KEPT: most common file shapes (eyeball for misses)')
    for extension, count in Counter(extension_of(p) for p in kept).most_common(12):
        print(f'    {extension:<16} {count:,}')

    suspects = find_suspects(paths, set(excluded))
    if suspects:
        print('\n  SUSPECTS -- machine-authored conventions NOT excluded')
        print('  (reported only; promoting one means a pattern + a test)')
        for label, matched in sorted(suspects.items(), key=lambda kv: -len(kv[1])):
            print(f'    {len(matched):>5}  {label}')
            for path in matched[:limit_suspects]:
                print(f'           {path}')
    else:
        print('\n  SUSPECTS       none')

    return {
        'repo': repo_url,
        'files': len(paths),
        'excluded': len(excluded),
        'fraction': fraction,
        'attributes': has_attributes,
        'suspects': {k: len(v) for k, v in suspects.items()},
        'commits': stats.commit_count,
        'bytes': stats.bytes_on_disk,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('repos', nargs='+', help='clone URLs')
    parser.add_argument('--root', type=Path,
                        default=Path(os.environ.get('REPOLENS_CLONE_ROOT', '.clones')))
    parser.add_argument('--limit-suspects', type=int, default=3)
    args = parser.parse_args(argv)

    require_git()
    store = CloneStore(root=args.root)

    results = []
    for repo_url in args.repos:
        try:
            results.append(audit(repo_url, store, args.limit_suspects))
        except CloneError as error:
            print(f'\n{repo_url}\n  FAILED: {error}', file=sys.stderr)

    if len(results) > 1:
        print(f'\n{"=" * 72}\nSUMMARY\n{"=" * 72}')
        print(f'  {"repo":<44} {"files":>7} {"excl":>7} {"pct":>7}  attrs')
        for row in results:
            name = str(row['repo']).rsplit('/', 2)[-2:]
            print(
                f'  {"/".join(name):<44} {row["files"]:>7,} '
                f'{row["excluded"]:>7,} {row["fraction"]:>6.1%}  '
                f'{"yes" if row["attributes"] else "no"}'
            )
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
