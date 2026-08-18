# RepoLens Development Guide

## Commands

Dependencies are managed with **uv**. `uv run` syncs the environment from
`uv.lock` before executing, so there is no activate step and no way to run
against a stale environment.

- Set up / sync: `uv sync`
- Run all tests: `uv run python -m unittest discover`
- Run single test: `uv run python -m unittest tests.test_analyzer` (module path, not a file path)
- Run app: `uv run python main.py`
- Add a dependency: `uv add <package>` (updates `pyproject.toml` and `uv.lock`)
- Add a dev dependency: `uv add --dev <package>`
- Re-resolve everything to newest: `uv lock --upgrade`
- Apply migrations: `uv run alembic upgrade head` (not `db.create_all()` — it
  cannot alter an existing table)
- Stamp an existing database at the baseline: `uv run alembic stamp e2cefdd6030c`
- New migration after a model change: `uv run alembic revision --autogenerate -m "..."`
- Run the substrate experiment: `uv run python experiments/001-substrate/run.py --limit 3`
- Fetch forge prose: `GITHUB_TOKEN=$(gh auth token) uv run python scripts/fetch_forge_text.py --limit 2`

`requirements.txt` and `requirements-dev.txt` are **generated**, not authored.
They exist so the pip path in the README keeps working and so scanners that
do not read `uv.lock` still see something. Regenerate after any dependency
change — two hand-maintained manifests drifting apart is what produced 38
open advisories on 2026-08-16:

```
uv export --format requirements-txt --no-dev --no-emit-project -o requirements.txt
uv export --format requirements-txt --no-emit-project -o requirements-dev.txt
```

`tests/__init__.py` must exist or `unittest discover` silently collects zero
tests and reports OK.

## Code Style Guidelines
- **Imports**: Group standard library, third-party, and local imports
- **Formatting**: Follow PEP 8 (4 spaces indentation, 88 char line length)
- **Types**: Use type hints on function signatures
- **Naming**: 
  - snake_case for variables/functions
  - CamelCase for classes
  - UPPERCASE for constants
- **Error handling**: Use specific exceptions with context messages
- **Documentation**: Docstrings for modules, classes, and functions
- **Testing**: Create unit tests for new functionality

## Project Structure
- Application code in `repolens/` directory
- Tests in `tests/` directory
- Flask templates in `templates/`
- Static assets in `static/` directory
- Schema migrations in `migrations/` (alembic)
- Local evidence in `experiments/NNN-slug/` — conjecture, calibrated gate,
  dated `log.jsonl`. The log is committed; it is the evidence trail.

## Substrate (RFC 028, M-1)
- `repolens/clones.py` — persistent bare-mirror clone store. Mirrors, not
  working trees: blame against an explicit revision works in a bare repo.
- `repolens/jobs.py` — checkpointed runner. At-least-once execution,
  exactly-once completion; safe because the work is idempotent (spec I4).
  Raise `JobAbort` (a `BaseException`) for conditions that will also fail the
  next item — quota, disk, credentials. A plain `Exception` fails one item.
- `repolens/forge.py` — GitHub PR bodies and review threads, bulk-paginated.
  `pr_number_from_commit` refuses bare `#123`: that's an issue reference, and
  a wrong PR association is a well-formed citation pointing at the wrong prose.
- `repolens/gitcheck.py` — git 2.40 is **required**, not detected.
  `create_app` and `IgnoreResolver` both call `require_git()` and raise. The
  degraded path still exists but must be asked for by name
  (`use_attributes=False`); silent degradation is how this repo has already
  been bitten twice.
- `repolens/ignores.py` — vendored/generated classification. Reads
  `.gitattributes`, *not* `.gitignore` (a tracked file was never ignored), and
  resolves at a revision, not HEAD — the same path classifies differently
  across commits. git does the resolution; pathspec only matches heuristics.
- Property tests, not example tests, guard both. Repository URLs are
  attacker-controlled and interruption schedules are unbounded, so
  `tests/test_clones.py` and `tests/test_jobs.py` generate their inputs.
- `tests/test_migrations.py::test_models_and_migrations_do_not_drift` fails
  the build if a model changes without a migration.

## Environment Setup
- DATABASE_URL: PostgreSQL connection string. Optional in development —
  `config.Config` falls back to `sqlite:///site.db` when it is unset.
- SECRET_KEY: optional; a random per-process key is generated when unset,
  which invalidates any session state across restarts.
- REPOLENS_CLONE_ROOT: where bare mirrors live (default `.clones`). These
  persist by design and grow without bound until an eviction policy exists.
- GITHUB_TOKEN: required by the forge client. Unauthenticated GitHub is 60
  requests/hour, which will not materialize one repository.