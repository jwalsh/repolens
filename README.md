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

- Python 3.11 or higher
- PostgreSQL database
- Git

### Installation

1. Clone the repository:
   ```bash
   git clone https://github.com/jwalsh/repolens.git
   cd repolens
   ```

2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
   
   Or using Poetry:
   ```bash
   poetry install
   ```

3. Set up environment variables:
   ```bash
   export DATABASE_URL="postgresql://username:password@localhost/repolens"
   ```

4. Run the application:
   ```bash
   python main.py
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

- Project Homepage: https://replit.com/@JasonWalsh1/RepoLens
- GitHub Repository: https://github.com/jwalsh/repolens