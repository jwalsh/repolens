"""Checkpointed, resumable job runner.

Substrate for the provenance lens (RFC 028, M-1). §10 of the spec states the
requirement plainly -- "parallelize by commit, cap concurrency, checkpoint by
sha so an interrupted backfill resumes" -- and nothing in the codebase
provided it. Packaging ran synchronously inside a POST handler.

*Delivery semantics, stated precisely because the imprecise version is a lie:*
this runner gives **at-least-once execution and exactly-once completion**. An
item interrupted mid-flight was never checkpointed, so a later run executes it
again. True exactly-once execution would require the work and its side effects
to commit in one transaction, which they do not.

That is safe here for a specific reason rather than by luck. Spec invariant I4
makes claim extraction a pure function of ``(commit_sha, prompt_version,
model_id)``, so re-executing an interrupted item is idempotent by
construction. Any work function handed to this runner is expected to hold the
same property. If yours does not, this runner is the wrong tool.

The checkpoint store is plain SQLite and holds no reference to Flask. A
backfill must be runnable from cron, from a worker process, and from a test,
none of which have an application context.
"""
from __future__ import annotations

import json
import sqlite3
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterator, Sequence

_SCHEMA = """
CREATE TABLE IF NOT EXISTS checkpoint (
    job_id     TEXT NOT NULL,
    item_id    TEXT NOT NULL,
    state      TEXT NOT NULL CHECK (state IN ('done', 'failed')),
    detail     TEXT,
    updated_at REAL NOT NULL,
    PRIMARY KEY (job_id, item_id)
);
CREATE INDEX IF NOT EXISTS ix_checkpoint_job_state ON checkpoint (job_id, state);
"""


class JobAbort(BaseException):
    """Stop the run now; keep every checkpoint written so far.

    ``BaseException``, not ``Exception``, and that is the entire point. The
    runner records a failing item and carries on, which is right for an error
    that is specific to one item and wrong for a condition that will fail the
    next item too -- an exhausted API quota, a full disk, a revoked token.
    Left as a plain ``Exception``, one rate limit marches through the corpus
    marking everything failed and burns the resume path it should have used.

    Raise this from a work function to convert "this item failed" into "come
    back later".
    """

    def __init__(self, reason: str, cause: BaseException | None = None) -> None:
        super().__init__(reason)
        self.reason = reason
        self.cause = cause


@dataclass(frozen=True)
class JobResult:
    """Outcome of one ``run_job`` call. Doubles as a measurement record."""

    job_id: str
    total: int
    executed: int  # items this run actually handed to `work`
    skipped: int  # items already checkpointed done before this run started
    failed: dict[str, str] = field(default_factory=dict)
    duration_seconds: float = 0.0

    @property
    def is_complete(self) -> bool:
        return not self.failed and self.executed + self.skipped == self.total


class CheckpointStore:
    """SQLite-backed completion log. Safe to share across threads."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        if self.path.parent != Path(""):
            self.path.parent.mkdir(parents=True, exist_ok=True)
        # One connection guarded by a lock rather than a connection per
        # thread: the write volume is one row per work item, and correctness
        # of the resume guarantee matters more than checkpoint throughput.
        self._lock = threading.Lock()
        self._connection = sqlite3.connect(str(self.path), check_same_thread=False)
        self._connection.executescript(_SCHEMA)
        self._connection.commit()

    def close(self) -> None:
        with self._lock:
            self._connection.close()

    def __enter__(self) -> "CheckpointStore":
        return self

    def __exit__(self, *_exc_info: object) -> None:
        self.close()

    # ---------------------------------------------------------------- reads

    def completed(self, job_id: str) -> set[str]:
        with self._lock:
            rows = self._connection.execute(
                "SELECT item_id FROM checkpoint WHERE job_id = ? AND state = 'done'",
                (job_id,),
            ).fetchall()
        return {row[0] for row in rows}

    def failures(self, job_id: str) -> dict[str, str]:
        with self._lock:
            rows = self._connection.execute(
                "SELECT item_id, detail FROM checkpoint "
                "WHERE job_id = ? AND state = 'failed'",
                (job_id,),
            ).fetchall()
        return {item_id: detail or "" for item_id, detail in rows}

    # --------------------------------------------------------------- writes

    def mark_done(self, job_id: str, item_id: str) -> None:
        self._upsert(job_id, item_id, "done", None)

    def mark_failed(self, job_id: str, item_id: str, detail: str) -> None:
        self._upsert(job_id, item_id, "failed", detail[:2000])

    def reset(self, job_id: str) -> None:
        with self._lock:
            self._connection.execute(
                "DELETE FROM checkpoint WHERE job_id = ?", (job_id,)
            )
            self._connection.commit()

    def _upsert(self, job_id: str, item_id: str, state: str, detail: str | None) -> None:
        with self._lock:
            self._connection.execute(
                "INSERT INTO checkpoint (job_id, item_id, state, detail, updated_at) "
                "VALUES (?, ?, ?, ?, ?) "
                "ON CONFLICT (job_id, item_id) DO UPDATE SET "
                "state = excluded.state, detail = excluded.detail, "
                "updated_at = excluded.updated_at",
                (job_id, item_id, state, detail, time.time()),
            )
            self._connection.commit()


def run_job(
    job_id: str,
    items: Sequence[str],
    work: Callable[[str], object],
    store: CheckpointStore,
    *,
    max_workers: int = 1,
    retry_failed: bool = True,
    on_progress: Callable[[str, int, int], None] | None = None,
) -> JobResult:
    """Run ``work`` over ``items``, skipping anything already checkpointed.

    ``work`` raising ``Exception`` marks that item failed and the run
    continues. ``BaseException`` -- ``JobAbort``, KeyboardInterrupt,
    SystemExit, a process signal -- propagates and aborts the run, which is
    what makes the resume path the normal path rather than an error path.

    Raise ``JobAbort`` for conditions that will also fail the next item.
    """
    started = time.monotonic()
    already_done = store.completed(job_id)
    previously_failed = store.failures(job_id)

    pending = [
        item
        for item in items
        if item not in already_done
        and (retry_failed or item not in previously_failed)
    ]
    skipped = len(items) - len(pending)

    executed = 0
    failed: dict[str, str] = {}
    counter_lock = threading.Lock()

    def run_one(item_id: str) -> None:
        nonlocal executed
        try:
            work(item_id)
        except Exception as error:  # noqa: BLE001 - recorded, not swallowed
            store.mark_failed(job_id, item_id, f"{type(error).__name__}: {error}")
            with counter_lock:
                failed[item_id] = f"{type(error).__name__}: {error}"
                executed += 1
        else:
            store.mark_done(job_id, item_id)
            with counter_lock:
                executed += 1
        finally:
            if on_progress is not None:
                on_progress(item_id, executed, len(pending))

    if max_workers <= 1:
        for item_id in pending:
            run_one(item_id)
    else:
        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            # list() forces every future to be awaited, so a BaseException
            # raised in a worker surfaces here instead of being discarded.
            list(pool.map(run_one, pending))

    return JobResult(
        job_id=job_id,
        total=len(items),
        executed=executed,
        skipped=skipped,
        failed=failed,
        duration_seconds=time.monotonic() - started,
    )


def resume_until_complete(
    job_id: str,
    items: Sequence[str],
    work: Callable[[str], object],
    store: CheckpointStore,
    *,
    max_attempts: int = 3,
    max_workers: int = 1,
) -> JobResult:
    """Re-run a job until nothing is left pending or attempts run out.

    Bounded deliberately: an unbounded retry against a permanently failing
    item is an infinite loop that looks like progress.
    """
    result = run_job(job_id, items, work, store, max_workers=max_workers)
    attempt = 1
    while not result.is_complete and attempt < max_attempts:
        attempt += 1
        result = run_job(job_id, items, work, store, max_workers=max_workers)
    return result


def iter_commits(clone_path: str | Path) -> Iterator[str]:
    """Commit shas from a bare mirror, newest first.

    Streamed rather than materialised: §10 budgets for 50k commits and the
    current packager builds the whole list in memory before writing it to a
    single JSON column.
    """
    process = subprocess.Popen(
        ["git", "--git-dir", str(clone_path), "rev-list", "HEAD"],
        stdout=subprocess.PIPE,
        text=True,
    )
    assert process.stdout is not None
    try:
        for line in process.stdout:
            sha = line.strip()
            if sha:
                yield sha
    finally:
        process.stdout.close()
        process.wait()


def dump_result(result: JobResult) -> str:
    """JSON line for the experiment log."""
    return json.dumps(
        {
            "job_id": result.job_id,
            "total": result.total,
            "executed": result.executed,
            "skipped": result.skipped,
            "failed_count": len(result.failed),
            "duration_seconds": round(result.duration_seconds, 3),
            "complete": result.is_complete,
        },
        sort_keys=True,
    )
