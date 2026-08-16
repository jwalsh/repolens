# RepoLens Development Guide

## Commands
- Run all tests: `python -m unittest discover`
- Run single test: `python -m unittest tests.test_analyzer` (module path, not a file path)
- Run app: `python main.py`
- Install dependencies: `python -m pip install -r requirements.txt`
- Install with Poetry: `poetry install`
- Create database tables: `python -c "import main; from repolens.database import db; main.app.app_context().push(); db.create_all()"`

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

## Environment Setup
- DATABASE_URL: PostgreSQL connection string. Optional in development —
  `config.Config` falls back to `sqlite:///site.db` when it is unset.
- SECRET_KEY: optional; a random per-process key is generated when unset,
  which invalidates any session state across restarts.