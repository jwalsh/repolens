"""Experiment 001 harness tests.

These verify the *instrument*, not the conjecture. They run against local
fixture repositories and never touch the network, so they establish that
measurement and gate evaluation work — and they deliberately do not establish
that C1 holds, which requires the real corpus.

The distinction matters: a green suite here means "the gate would fire
correctly if you ran it", not "the substrate is fast enough".
"""
from __future__ import annotations

import importlib.util
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
RUN_PY = REPO_ROOT / 'experiments' / '001-substrate' / 'run.py'


def _load_run_module():
    # The experiment directory is not an importable package name (it starts
    # with a digit), so load the script by path.
    spec = importlib.util.spec_from_file_location('experiment_001_run', RUN_PY)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    # Registered before exec: @dataclass resolves string annotations through
    # sys.modules, and run.py uses `from __future__ import annotations`.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


run = _load_run_module()

from tests._fixtures import make_repo  # noqa: E402


class TestCorpusParsing(unittest.TestCase):
    def test_skips_comments_and_blank_lines(self):
        with tempfile.TemporaryDirectory() as work_dir:
            corpus = Path(work_dir) / 'corpus.txt'
            corpus.write_text(
                '# a comment\n'
                '\n'
                'https://example.com/a.git\n'
                '   \n'
                '  https://example.com/b.git  \n'
                '# trailing comment\n'
            )

            urls = run.read_corpus(corpus)

            self.assertEqual(
                urls, ['https://example.com/a.git', 'https://example.com/b.git']
            )

    def test_limit_truncates(self):
        with tempfile.TemporaryDirectory() as work_dir:
            corpus = Path(work_dir) / 'corpus.txt'
            corpus.write_text('a\nb\nc\n')

            self.assertEqual(run.read_corpus(corpus, limit=2), ['a', 'b'])

    def test_shipped_corpus_has_twenty_repositories(self):
        # R1 specifies 20 repos. If the corpus drifts from that, the study's
        # median is computed over a different population than the spec claims.
        urls = run.read_corpus(RUN_PY.parent / 'corpus.txt')

        self.assertEqual(len(urls), 20)
        self.assertEqual(len(set(urls)), 20)


class TestGateEvaluation(unittest.TestCase):
    def test_upheld_when_everything_is_within_budget(self):
        measurement = run.Measurement(
            corpus_size=3,
            cold_seconds=10.0,
            warm_seconds=1.0,
            disk_bytes=1024,
            repos_measured=3,
        )

        verdict = run.evaluate(measurement)

        self.assertTrue(verdict['upheld'])
        self.assertTrue(all(verdict['predictions'].values()))

    def test_disk_over_budget_refutes_p1_1(self):
        measurement = run.Measurement(
            corpus_size=3, disk_bytes=run.DISK_BUDGET_BYTES + 1
        )

        verdict = run.evaluate(measurement)

        self.assertFalse(verdict['predictions']['P1.1_disk'])
        self.assertFalse(verdict['upheld'])

    def test_slow_cold_pass_refutes_p1_2(self):
        measurement = run.Measurement(
            corpus_size=3, cold_seconds=run.COLD_BUDGET_SECONDS + 1
        )

        verdict = run.evaluate(measurement)

        self.assertFalse(verdict['predictions']['P1.2_cold'])
        self.assertFalse(verdict['upheld'])

    def test_an_unclonable_repo_refutes_regardless_of_budgets(self):
        measurement = run.Measurement(
            corpus_size=3,
            cold_seconds=1.0,
            warm_seconds=1.0,
            disk_bytes=1024,
            failures={'https://example.com/gone.git': 'CloneError: not found'},
        )

        verdict = run.evaluate(measurement)

        self.assertTrue(all(verdict['predictions'].values()))
        self.assertFalse(verdict['corpus_complete'])
        self.assertFalse(verdict['upheld'])


class TestEndToEnd(unittest.TestCase):
    def test_run_against_local_fixtures_upholds_and_logs(self):
        with tempfile.TemporaryDirectory() as work_dir:
            sources = [
                make_repo(os.path.join(work_dir, f'repo{index}'), commits=3)
                for index in range(3)
            ]
            corpus = Path(work_dir) / 'corpus.txt'
            corpus.write_text('# local fixtures\n' + '\n'.join(sources) + '\n')
            log = Path(work_dir) / 'log.jsonl'

            exit_code = run.main([
                '--corpus', str(corpus),
                '--root', os.path.join(work_dir, 'clones'),
                '--log', str(log),
                '--workers', '2',
            ])

            self.assertEqual(exit_code, 0)

            entries = [json.loads(line) for line in log.read_text().splitlines()]
            self.assertEqual(len(entries), 1)
            entry = entries[0]

            self.assertTrue(entry['upheld'])
            self.assertEqual(entry['repos_measured'], 3)
            self.assertEqual(entry['commit_total'], 9)
            self.assertGreater(entry['disk_bytes'], 0)
            self.assertFalse(entry['resumed'])
            self.assertEqual(entry['conjecture'], 'C1')

    def test_log_is_append_only(self):
        with tempfile.TemporaryDirectory() as work_dir:
            source = make_repo(os.path.join(work_dir, 'repo'), commits=2)
            corpus = Path(work_dir) / 'corpus.txt'
            corpus.write_text(source + '\n')
            log = Path(work_dir) / 'log.jsonl'
            argv = [
                '--corpus', str(corpus),
                '--root', os.path.join(work_dir, 'clones'),
                '--log', str(log),
            ]

            run.main(argv)
            run.main(argv)

            # A gate whose history can be overwritten is not evidence.
            self.assertEqual(len(log.read_text().strip().splitlines()), 2)

    def test_a_failing_repo_makes_the_run_exit_nonzero(self):
        with tempfile.TemporaryDirectory() as work_dir:
            good = make_repo(os.path.join(work_dir, 'good'), commits=2)
            corpus = Path(work_dir) / 'corpus.txt'
            corpus.write_text(f'{good}\n{work_dir}/does-not-exist\n')
            log = Path(work_dir) / 'log.jsonl'

            exit_code = run.main([
                '--corpus', str(corpus),
                '--root', os.path.join(work_dir, 'clones'),
                '--log', str(log),
            ])

            self.assertEqual(exit_code, 1)
            entry = json.loads(log.read_text().splitlines()[0])
            self.assertFalse(entry['corpus_complete'])
            self.assertEqual(len(entry['failures']), 1)


if __name__ == '__main__':
    unittest.main()
