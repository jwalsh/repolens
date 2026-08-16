#!/usr/bin/env python
"""Experiment 001 — substrate feasibility. Executable gate.

Reads a corpus of repository URLs, materializes them through the clone store
under the checkpointed runner, measures cold and warm cost, evaluates the
calibrated gate, and appends a dated record to ``log.jsonl``.

Exit status is the verdict: 0 upheld, 1 refuted. That is deliberate — a gate
you have to read prose to interpret is a gate that stops being checked.

    python experiments/001-substrate/run.py --limit 3
    python experiments/001-substrate/run.py            # full corpus
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1]))

from repolens.clones import CloneStats, CloneStore  # noqa: E402
from repolens.jobs import CheckpointStore, run_job  # noqa: E402

# ---------------------------------------------------------------- the gate
#
# These constants ARE the calibration. README.org describes them; this is
# where they live, so the description cannot drift from what is enforced.

DISK_BUDGET_BYTES = 4 * 1024**3  # P1.1
COLD_BUDGET_SECONDS = 1800.0  # P1.2
WARM_BUDGET_SECONDS = 180.0  # P1.3


@dataclass
class Measurement:
    corpus_size: int
    cold_seconds: float = 0.0
    warm_seconds: float = 0.0
    disk_bytes: int = 0
    commit_total: int = 0
    repos_measured: int = 0
    failures: dict[str, str] = field(default_factory=dict)

    @property
    def bytes_per_commit(self) -> float:
        return self.disk_bytes / self.commit_total if self.commit_total else 0.0


def read_corpus(path: Path, limit: int | None = None) -> list[str]:
    urls: list[str] = []
    for line in path.read_text().splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith('#'):
            urls.append(stripped)
    return urls[:limit] if limit else urls


def measure(
    repo_urls: list[str],
    store: CloneStore,
    checkpoints: CheckpointStore,
    *,
    workers: int = 4,
    run_warm_pass: bool = True,
) -> Measurement:
    """Materialize the corpus twice: cold (clone) then warm (fetch only)."""
    measurement = Measurement(corpus_size=len(repo_urls))
    stats: dict[str, CloneStats] = {}
    stats_lock = threading.Lock()

    def materialize(repo_url: str) -> None:
        result = store.ensure(repo_url)
        with stats_lock:
            stats[repo_url] = result

    cold_started = time.monotonic()
    cold = run_job(
        'substrate-cold', repo_urls, materialize, checkpoints, max_workers=workers
    )
    measurement.cold_seconds = time.monotonic() - cold_started
    measurement.failures.update(cold.failed)

    if run_warm_pass:
        warm_started = time.monotonic()
        warm = run_job(
            'substrate-warm', repo_urls, materialize, checkpoints,
            max_workers=workers,
        )
        measurement.warm_seconds = time.monotonic() - warm_started
        measurement.failures.update(warm.failed)

    measurement.disk_bytes = store.disk_usage_bytes()
    measurement.commit_total = sum(stat.commit_count for stat in stats.values())
    measurement.repos_measured = len(stats)
    return measurement


def evaluate(measurement: Measurement) -> dict[str, object]:
    """Apply the calibrated gate. Returns per-prediction verdicts."""
    predictions = {
        'P1.1_disk': measurement.disk_bytes <= DISK_BUDGET_BYTES,
        'P1.2_cold': measurement.cold_seconds <= COLD_BUDGET_SECONDS,
        'P1.3_warm': measurement.warm_seconds <= WARM_BUDGET_SECONDS,
    }
    # A repository that would not clone is not a budget question, but it does
    # mean the corpus was not materialized, so the run cannot uphold C1.
    corpus_complete = not measurement.failures

    return {
        'predictions': predictions,
        'corpus_complete': corpus_complete,
        'upheld': all(predictions.values()) and corpus_complete,
    }


def record(
    measurement: Measurement,
    verdict: dict[str, object],
    corpus: str = '',
) -> dict[str, object]:
    return {
        'experiment': '001-substrate',
        'conjecture': 'C1',
        'at': datetime.now(timezone.utc).isoformat(timespec='seconds'),
        # Which corpus produced these numbers. Without it a two-repo smoke
        # run and the twenty-repo study are indistinguishable in the log.
        'corpus': corpus,
        'corpus_size': measurement.corpus_size,
        'repos_measured': measurement.repos_measured,
        'commit_total': measurement.commit_total,
        'disk_bytes': measurement.disk_bytes,
        'bytes_per_commit': round(measurement.bytes_per_commit, 1),
        'cold_seconds': round(measurement.cold_seconds, 1),
        'warm_seconds': round(measurement.warm_seconds, 1),
        'budgets': {
            'disk_bytes': DISK_BUDGET_BYTES,
            'cold_seconds': COLD_BUDGET_SECONDS,
            'warm_seconds': WARM_BUDGET_SECONDS,
        },
        'failures': measurement.failures,
        **verdict,
    }


def append_log(log_path: Path, entry: dict[str, object]) -> None:
    """Append-only. A gate whose history can be overwritten is not evidence."""
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open('a') as handle:
        handle.write(json.dumps(entry, sort_keys=True) + '\n')


def _format(entry: dict[str, object]) -> str:
    predictions = entry['predictions']  # type: ignore[index]
    lines = [
        f"corpus        {entry['repos_measured']}/{entry['corpus_size']} repos, "
        f"{entry['commit_total']:,} commits",
        f"disk          {int(entry['disk_bytes']) / 1024**3:.2f} GiB "
        f"({entry['bytes_per_commit']} B/commit)",
        f"cold          {entry['cold_seconds']}s",
        f"warm          {entry['warm_seconds']}s",
        '',
    ]
    for name, passed in predictions.items():  # type: ignore[union-attr]
        lines.append(f"  {'PASS' if passed else 'FAIL'}  {name}")
    if not entry['corpus_complete']:
        lines.append(f"  FAIL  corpus_complete ({len(entry['failures'])} failed)")
    lines.append('')
    lines.append('C1 UPHELD' if entry['upheld'] else 'C1 REFUTED')
    return '\n'.join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--corpus', type=Path, default=HERE / 'corpus.txt')
    parser.add_argument('--limit', type=int, default=None)
    parser.add_argument(
        '--root', type=Path, default=Path(os.environ.get('REPOLENS_CLONE_ROOT', '.clones')),
    )
    parser.add_argument('--workers', type=int, default=4)
    parser.add_argument('--log', type=Path, default=HERE / 'log.jsonl')
    parser.add_argument(
        '--resume',
        action='store_true',
        help=(
            'Continue an interrupted materialization instead of remeasuring '
            'from scratch. The timings from a resumed run are not comparable '
            'to a full pass and should not be logged as one.'
        ),
    )
    args = parser.parse_args(argv)

    repo_urls = read_corpus(args.corpus, args.limit)
    if not repo_urls:
        parser.error(f'no repository URLs in {args.corpus}')

    store = CloneStore(root=args.root)
    with CheckpointStore(args.root / 'checkpoints.sqlite') as checkpoints:
        if not args.resume:
            # Fresh timing by default; the checkpoints exist so an interrupted
            # run can be finished, not so a completed run reports zero seconds.
            checkpoints.reset('substrate-cold')
            checkpoints.reset('substrate-warm')
        measurement = measure(
            repo_urls, store, checkpoints, workers=args.workers
        )

    entry = record(measurement, evaluate(measurement), corpus=str(args.corpus))
    entry['resumed'] = args.resume
    append_log(args.log, entry)
    print(_format(entry))
    return 0 if entry['upheld'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
