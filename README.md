# RepoLens

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](https://opensource.org/licenses/MIT)

A standardized system to package, present, and analyze project repositories.

## Overview

RepoLens helps you gain insights into your software projects by analyzing repository structure, commit patterns, and codebase metrics. Whether you're evaluating project health, understanding contribution patterns, or extracting key metrics, RepoLens provides a standardized approach to repository analysis.

## Features

- **Repository Analysis**: Track file counts, commit history, branch structures
- **File Type Analysis**: Understand your codebase composition by file types
- **Web Interface**: Intuitive dashboard for viewing repository metrics
- **API Access**: Programmatic access to repository data and analysis

## Getting Started

### Prerequisites

- **Git 2.40 or newer.** Enforced, not suggested: the app refuses to start on
  anything older. `check-attr --source` arrived in 2.40 and is how vendored
  and generated files are classified at a revision rather than at HEAD.
  Without it the answers get quietly worse, which is harder to notice than a
  crash.
- **[uv](https://docs.astral.sh/uv/)** — manages Python and dependencies. The
  required version is declared as `required-version` in `pyproject.toml` and
  uv enforces it itself.
- PostgreSQL, optional — falls back to SQLite when `DATABASE_URL` is unset

### Installation

1. Clone the repository:
   ```bash
   git clone https://github.com/jwalsh/repolens.git
   cd repolens
   ```

2. Install dependencies:
   ```bash
   uv sync
   ```

   uv provisions Python 3.11+ itself, so no separate interpreter setup is
   needed. If you would rather use pip, `requirements.txt` is a hash-pinned
   export of the same lock:
   ```bash
   pip install -r requirements.txt
   ```

3. Set up environment variables (all optional in development):
   ```bash
   export DATABASE_URL="postgresql://username:password@localhost/repolens"
   export REPOLENS_CLONE_ROOT=".clones"   # where bare mirrors are kept
   export GITHUB_TOKEN="$(gh auth token)" # only for the forge client
   ```

4. Apply migrations and run the application:
   ```bash
   uv run alembic upgrade head
   uv run python main.py
   ```

5. Access the web interface at http://localhost:5000

## Usage

1. Add repositories for analysis via the web interface
2. View detailed metrics for each repository
3. Export analysis data or access via API endpoints

## Contributing

We welcome contributions! Please see our [DEVELOPER.md](DEVELOPER.md) for guidelines on how to contribute to this project.

## License

This project is licensed under the MIT License - see the LICENSE file for details.

## Contact

- GitHub Repository: https://github.com/jwalsh/repolens