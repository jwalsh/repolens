"""Shared test fixtures.

Local git repositories only. A unit test that clones over the network is a
network test wearing a unit test's name, and it was one of the defects this
suite started with.
"""
from __future__ import annotations

import os
import subprocess


def git(*argv: str, cwd: str) -> str:
    completed = subprocess.run(
        ['git', *argv], cwd=cwd, check=True, capture_output=True, text=True
    )
    return completed.stdout.strip()


def make_repo(path: str, commits: int = 2) -> str:
    """Create a small local git repo. Returns its path."""
    os.makedirs(path, exist_ok=True)
    git('init', '-q', '-b', 'main', '.', cwd=path)
    git('config', 'user.email', 'test@example.com', cwd=path)
    git('config', 'user.name', 'Test', cwd=path)

    for index in range(commits):
        filename = os.path.join(path, f'file{index}.txt')
        with open(filename, 'w') as handle:
            handle.write(f'line {index}\n')
        git('add', '-A', cwd=path)
        git('commit', '-q', '-m', f'commit {index}', cwd=path)

    return path


def add_commit(path: str, message: str = 'extra') -> str:
    """Append one commit to an existing repo. Returns the new sha."""
    filename = os.path.join(path, 'extra.txt')
    with open(filename, 'a') as handle:
        handle.write(f'{message}\n')
    git('add', '-A', cwd=path)
    git('commit', '-q', '-m', message, cwd=path)
    return git('rev-parse', 'HEAD', cwd=path)
