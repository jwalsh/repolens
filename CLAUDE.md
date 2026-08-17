# RepoLens Development Guide

## Commands
- Run all tests: `python -m unittest discover`
- Run single test: `python -m unittest tests.test_analyzer` (module path, not a file path)
- Run app: `python main.py`
- Install dependencies: `python -m pip install -r requirements.txt`
- Install dev/test dependencies: `python -m pip install -r requirements-dev.txt`
- Install with Poetry: `poetry install`
- Apply migrations: `alembic upgrade head` (not `db.create_all()` — it cannot
  alter an existing table)
- Stamp an existing database at the baseline: `alembic stamp e2cefdd6030c`
- New migration after a model change: `alembic revision --autogenerate -m "..."`
- Run the substrate experiment: `python experiments/001-substrate/run.py --limit 3`
- Fetch forge prose: `GITHUB_TOKEN=$(gh auth token) python scripts/fetch_forge_text.py --limit 2`

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