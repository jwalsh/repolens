# RepoLens Development Guide

## Commands
- Run all tests: `python -m unittest discover`
- Run single test: `python -m unittest tests/test_file.py`
- Run app: `python main.py`
- Install dependencies: `pip install -e .` or `python -m pip install -r requirements.txt`
- Install with Poetry: `poetry install`
- Run with development server: `python main.py`
- Create database tables: `python -c "from main import app; from repolens.database import db; with app.app_context(): db.create_all()"`

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
- DATABASE_URL: PostgreSQL connection string required for database operations