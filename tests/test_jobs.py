"""Job runner tests.

The resume guarantee is the reason this module exists, and it is not
example-testable: "does an interrupted backfill resume correctly" is a claim
about every possible interruption point, not about the three a human picks.
So the interruption schedule is generated.

The property being checked is the one the runner actually offers -- at-least-
once execution, exactly-once completion -- rather than the stronger claim it
would be convenient to make.
"""
from __future__ import annotations

import os
import string
import tempfile
import unittest
from collections import Counter

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from repolens.jobs import CheckpointStore, JobResult, run_job, resume_until_complete
from repolens.jobs import dump_result, iter_commits
from tests._fixtures import make_repo


class Interrupt(BaseException):
    """Stands in for process death.

    BaseException, not Exception, so ``run_job`` does not catch it and record
    a per-item failure. That distinction is the runner's contract: recoverable
    work errors are checkpointed as failures, process death is not
    checkpointed at all.
    """


ITEM_IDS = st.lists(
    st.text(alphabet=string.hexdigits.lower(), min_size=4, max_size=8),
    min_size=1,
    max_size=25,
    unique=True,
)

# Each entry is how many items a run manages before dying. 0 means it dies
# immediately; a large value means it runs to completion.
INTERRUPT_SCHEDULE = st.lists(
    st.integers(min_value=0, max_value=8), min_size=0, max_size=8
)


class TestResumeProperties(unittest.TestCase):
    @settings(
        max_examples=60,
        deadline=None,
        suppress_health_check=[HealthCheck.function_scoped_fixture],
    )
    @given(items=ITEM_IDS, schedule=INTERRUPT_SCHEDULE)
    def test_resume_completes_every_item_exactly_once(self, items, schedule):
        with tempfile.TemporaryDirectory() as work_dir:
            store = CheckpointStore(os.path.join(work_dir, 'checkpoints.sqlite'))
            invocations: Counter[str] = Counter()
            resumed_already_done: list[str] = []
            interrupted_runs = 0

            def make_work(budget: int):
                remaining = [budget]

                def work(item_id: str) -> None:
                    # Order matters: the side effect lands BEFORE the process
                    # dies, which is what makes the item re-executable rather
                    # than merely un-started.
                    if item_id in store.completed('backfill'):
                        resumed_already_done.append(item_id)
                    invocations[item_id] += 1
                    if remaining[0] <= 0:
                        raise Interrupt(item_id)
                    remaining[0] -= 1

                return work

            for budget in schedule:
                try:
                    run_job('backfill', items, make_work(budget), store)
                except Interrupt:
                    interrupted_runs += 1

            final = run_job('backfill', items, make_work(10**6), store)

            # Exactly-once completion.
            self.assertEqual(store.completed('backfill'), set(items))
            self.assertEqual(store.failures('backfill'), {})
            self.assertTrue(final.is_complete)

            # At-least-once execution.
            for item_id in items:
                self.assertGreaterEqual(invocations[item_id], 1)

            # Tightness: the only re-executions are the items that were
            # in flight when a run died. One per interrupted run, at most.
            redundant = sum(count - 1 for count in invocations.values())
            self.assertLessEqual(redundant, interrupted_runs)

            # A checkpointed item is never handed to `work` again.
            self.assertEqual(resumed_already_done, [])

            store.close()

    @settings(
        max_examples=40,
        deadline=None,
        suppress_health_check=[HealthCheck.function_scoped_fixture],
    )
    @given(items=ITEM_IDS, schedule=INTERRUPT_SCHEDULE)
    def test_completed_set_only_grows(self, items, schedule):
        with tempfile.TemporaryDirectory() as work_dir:
            store = CheckpointStore(os.path.join(work_dir, 'checkpoints.sqlite'))
            seen: set[str] = set()

            def make_work(budget: int):
                remaining = [budget]

                def work(item_id: str) -> None:
                    if remaining[0] <= 0:
                        raise Interrupt(item_id)
                    remaining[0] -= 1

                return work

            for budget in schedule:
                try:
                    run_job('backfill', items, make_work(budget), store)
                except Interrupt:
                    pass
                now_done = store.completed('backfill')
                self.assertTrue(
                    seen <= now_done, 'a checkpointed item was un-completed'
                )
                seen = now_done

            store.close()

    @settings(
        max_examples=25,
        deadline=None,
        suppress_health_check=[HealthCheck.function_scoped_fixture],
    )
    @given(items=ITEM_IDS, workers=st.integers(min_value=2, max_value=6))
    def test_concurrency_does_not_break_completion(self, items, workers):
        with tempfile.TemporaryDirectory() as work_dir:
            store = CheckpointStore(os.path.join(work_dir, 'checkpoints.sqlite'))
            invocations: Counter[str] = Counter()
            lock_free_counter = Counter()

            def work(item_id: str) -> None:
                invocations[item_id] += 1
                lock_free_counter[item_id] += 1

            result = run_job(
                'backfill', items, work, store, max_workers=workers
            )

            self.assertEqual(store.completed('backfill'), set(items))
            self.assertEqual(result.executed, len(items))
            self.assertTrue(result.is_complete)
            for item_id in items:
                self.assertEqual(invocations[item_id], 1)

            store.close()


class TestFailureHandling(unittest.TestCase):
    def setUp(self):
        self.work_dir = tempfile.TemporaryDirectory()
        self.store = CheckpointStore(
            os.path.join(self.work_dir.name, 'checkpoints.sqlite')
        )

    def tearDown(self):
        self.store.close()
        self.work_dir.cleanup()

    def test_a_failing_item_does_not_stop_the_run(self):
        def work(item_id: str) -> None:
            if item_id == 'b':
                raise ValueError('boom')

        result = run_job('job', ['a', 'b', 'c'], work, self.store)

        self.assertEqual(self.store.completed('job'), {'a', 'c'})
        self.assertIn('b', result.failed)
        self.assertIn('boom', result.failed['b'])
        self.assertFalse(result.is_complete)

    def test_failures_are_retried_by_default(self):
        attempts = Counter()

        def work(item_id: str) -> None:
            attempts[item_id] += 1
            if item_id == 'b' and attempts['b'] == 1:
                raise ValueError('transient')

        run_job('job', ['a', 'b'], work, self.store)
        second = run_job('job', ['a', 'b'], work, self.store)

        self.assertEqual(self.store.completed('job'), {'a', 'b'})
        self.assertEqual(attempts['a'], 1)  # already done, not re-run
        self.assertEqual(attempts['b'], 2)
        self.assertTrue(second.is_complete)

    def test_retry_failed_false_skips_known_failures(self):
        def always_fails(item_id: str) -> None:
            raise ValueError('permanent')

        run_job('job', ['a'], always_fails, self.store)
        second = run_job(
            'job', ['a'], always_fails, self.store, retry_failed=False
        )

        self.assertEqual(second.executed, 0)
        self.assertEqual(second.skipped, 1)

    def test_resume_until_complete_is_bounded(self):
        attempts = Counter()

        def always_fails(item_id: str) -> None:
            attempts[item_id] += 1
            raise ValueError('permanent')

        result = resume_until_complete(
            'job', ['a'], always_fails, self.store, max_attempts=3
        )

        # Bounded on purpose: retrying a permanently failing item forever is
        # an infinite loop that looks like progress.
        self.assertEqual(attempts['a'], 3)
        self.assertFalse(result.is_complete)

    def test_reset_clears_the_job(self):
        run_job('job', ['a'], lambda item: None, self.store)
        self.assertEqual(self.store.completed('job'), {'a'})

        self.store.reset('job')

        self.assertEqual(self.store.completed('job'), set())

    def test_jobs_are_isolated_from_each_other(self):
        run_job('one', ['a'], lambda item: None, self.store)
        run_job('two', ['b'], lambda item: None, self.store)

        self.assertEqual(self.store.completed('one'), {'a'})
        self.assertEqual(self.store.completed('two'), {'b'})

    def test_checkpoints_survive_reopening_the_store(self):
        path = os.path.join(self.work_dir.name, 'persist.sqlite')
        with CheckpointStore(path) as store:
            run_job('job', ['a', 'b'], lambda item: None, store)

        with CheckpointStore(path) as reopened:
            self.assertEqual(reopened.completed('job'), {'a', 'b'})


class TestCommitStreaming(unittest.TestCase):
    def test_iter_commits_streams_a_bare_mirror(self):
        from repolens.clones import CloneStore

        with tempfile.TemporaryDirectory() as work_dir:
            source = make_repo(os.path.join(work_dir, 'source'), commits=5)
            store = CloneStore(root=os.path.join(work_dir, 'clones'))
            stats = store.ensure(source)

            shas = list(iter_commits(stats.path))

            self.assertEqual(len(shas), 5)
            self.assertEqual(shas[0], stats.head_sha)
            self.assertTrue(all(len(sha) == 40 for sha in shas))


class TestMeasurement(unittest.TestCase):
    def test_dump_result_is_a_json_line(self):
        import json

        result = JobResult(
            job_id='job', total=3, executed=2, skipped=1, duration_seconds=1.5
        )
        record = json.loads(dump_result(result))

        self.assertEqual(record['total'], 3)
        self.assertTrue(record['complete'])
        self.assertNotIn('\n', dump_result(result))


if __name__ == '__main__':
    unittest.main()
