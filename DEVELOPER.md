# RepoLens Developer Guide

This guide covers everything you need to know to contribute to and develop the RepoLens project.

## Project Structure

```
repolens/
├── repolens/            # Core application code
│   ├── __init__.py      # Package marker only -- no db instance lives here
│   ├── analyzer.py      # Repository analysis logic
│   ├── api.py           # API endpoints
│   ├── clones.py        # Persistent bare-mirror clone store
│   ├── database.py      # The single SQLAlchemy instance
│   ├── forge.py         # GitHub PR bodies and review threads
│   ├── jobs.py          # Checkpointed, resumable job runner
│   ├── models.py        # Data models
│   └── packager.py      # Repository data packaging
├── migrations/          # Alembic revisions
├── experiments/         # Registered conjectures, gates, dated logs
├── static/              # Static assets (CSS, JS)
├── templates/           # HTML templates
├── tests/               # Test suite
├── docs/                # Documentation and RFCs
└── scripts/             # Utility scripts
```

## Development Environment Setup

1. Clone the repository:
   ```bash
   git clone https://github.com/jwalsh/repolens.git
   cd repolens
   ```

2. Install dependencies:
   ```bash
   uv sync
   ```

   uv creates and manages `.venv` itself and provisions a suitable Python.
   There is no activate step: `uv run <command>` syncs from `uv.lock` first,
   so it is not possible to run against a stale environment.

3. Set up local database (optional — SQLite is the fallback):
   ```bash
   export DATABASE_URL="postgresql://username:password@localhost/repolens"
   ```

4. Apply migrations and run the application:
   ```bash
   uv run alembic upgrade head
   uv run python main.py
   ```

## Dependencies

`pyproject.toml` and `uv.lock` are the source of truth.

```bash
uv add <package>          # runtime dependency
uv add --dev <package>    # test/dev dependency
uv lock --upgrade         # re-resolve everything to newest
```

`requirements.txt` and `requirements-dev.txt` are **generated** hash-pinned
exports, kept so the pip path and dependency scanners still work. Regenerate
them after any dependency change:

```bash
uv export --format requirements-txt --no-dev --no-emit-project -o requirements.txt
uv export --format requirements-txt --no-emit-project -o requirements-dev.txt
```

Do not hand-edit them. Two independently maintained manifests drifting apart
is exactly what left 38 advisories open against the old `poetry.lock`.

CI verifies these are current, and **pins uv to the version in
`.github/workflows/ci.yml`** — uv changes its export output between releases
(0.6 emitted no `# via` annotations, 0.12 does), so an unpinned uv would make
the check depend on whichever version the runner installed. If your local uv
differs from the pinned one, the exports you generate will not match CI's.
Check with `uv --version`, and bump the pin and regenerate in the same commit.

## Testing

Run the full test suite:
```bash
uv run python -m unittest discover
```

Run a specific test module (module path, not a file path):
```bash
uv run python -m unittest tests.test_analyzer
```

`tests/__init__.py` must exist or discovery silently collects zero tests and
reports OK.

## Code Style Guidelines

RepoLens follows these coding standards:

- **Python Version**: 3.11+
- **Formatting**: PEP 8 compliant with a line length of 88 characters
- **Imports**: Group imports in the following order:
  1. Standard library imports
  2. Third-party imports
  3. Local application imports
- **Naming Conventions**:
  - `snake_case` for variables, functions, and methods
  - `CamelCase` for classes
  - `UPPERCASE` for constants
- **Documentation**: Docstrings for all modules, classes, and functions
- **Type Hints**: Use type annotations for function signatures
- **Error Handling**: Use specific exceptions with contextual error messages

## Pull Request Process

1. Create a new branch for your feature or bugfix
2. Implement your changes with appropriate tests
3. Run the test suite to ensure all tests pass
4. Submit a pull request with a clear description of changes
5. Address any feedback from code review

## Common Development Tasks

### Adding a New Analysis Type

1. Update `repolens/analyzer.py` with the new analysis logic
2. Add appropriate tests in `tests/test_analyzer.py`
3. Update API documentation if exposing via API

### Modifying Database Models

1. Update the model definitions in `repolens/models.py`
2. Run the application to apply migrations (automatic with Flask-SQLAlchemy)
3. Update any affected API endpoints or analysis functions

## Documentation

Keep documentation up-to-date when making changes:

- Update docstrings for any modified code
- Update README.md for user-facing changes
- Update DEVELOPER.md for development workflow changes

## Resources

- [Flask Documentation](https://flask.palletsprojects.com/)
- [SQLAlchemy Documentation](https://docs.sqlalchemy.org/)
- [Alembic Documentation](https://alembic.sqlalchemy.org/)
- [Hypothesis Documentation](https://hypothesis.readthedocs.io/)
- [git plumbing](https://git-scm.com/docs) — RepoLens invokes git directly
  rather than through a binding, because `--mirror`, `ls-tree -z` and
  `blame --line-porcelain` are what the provenance lens needs.