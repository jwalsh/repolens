# RepoLens Developer Guide

This guide covers everything you need to know to contribute to and develop the RepoLens project.

## Project Structure

```
repolens/
├── repolens/            # Core application code
│   ├── __init__.py
│   ├── analyzer.py      # Repository analysis logic
│   ├── api.py           # API endpoints
│   ├── database.py      # Database models and connection
│   ├── models.py        # Data models
│   ├── packager.py      # Repository data packaging
│   └── utils.py         # Utility functions
├── static/              # Static assets (CSS, JS)
├── templates/           # HTML templates
├── tests/               # Test suite
├── docs/                # Documentation
└── scripts/             # Utility scripts
```

## Development Environment Setup

1. Clone the repository:
   ```bash
   git clone https://github.com/jwalsh/repolens.git
   cd repolens
   ```

2. Set up a virtual environment:
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```

3. Install dependencies:
   ```bash
   pip install -e .  # Install in development mode
   # OR
   poetry install
   ```

4. Set up local database:
   ```bash
   export DATABASE_URL="postgresql://username:password@localhost/repolens"
   ```

5. Run the application in development mode:
   ```bash
   python main.py
   ```

## Testing

Run the full test suite:
```bash
python -m unittest discover
```

Run a specific test file:
```bash
python -m unittest tests/test_analyzer.py
```

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
- [GitPython Documentation](https://gitpython.readthedocs.io/)