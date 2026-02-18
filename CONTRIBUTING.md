# Contributing to Daily Blog

Thank you for your interest in contributing to the daily-blog project! This guide will help you get started.

## Getting Started

### Prerequisites

- Python 3.11 or higher
- Git

### Development Setup

1. Clone the repository:

```bash
git clone <repository-url>
cd daily-blog
```

2. Set up the development environment:

```bash
make setup
```

This creates a virtual environment at `.venv` and installs all development dependencies.

3. Copy the environment template:

```bash
cp .env.example .env
```

4. Activate the virtual environment:

```bash
source .venv/bin/activate
```

## Development Workflow

### Running Tests

Run all tests:

```bash
make test
```

### Code Quality

Lint the codebase:

```bash
make lint
```

Run type checking:

```bash
make typecheck
```

Run all checks together:

```bash
make check
```

### Pre-commit Hooks

Install pre-commit hooks to automatically run checks before committing:

```bash
.venv/bin/pre-commit install
```

Pre-commit will automatically:
- Format code with ruff
- Run ruff linter
- Run basedpyright type checker

### Running the Pipeline

Run the full pipeline:

```bash
make run
```

Or run individual components:

```bash
python3 ingest_rss.py    # Ingest RSS feeds
python3 score_rss.py     # Score and filter articles
python3 run_pipeline.py  # Full pipeline
```

## Project Structure

```
daily-blog/
├── config/              # Configuration files (rules engine, model routing)
├── data/                # Generated data (database, outputs)
├── docs/                # Documentation
├── ops/                 # Operational scripts (cron, runbooks)
├── scripts/             # Utility scripts
├── tests/               # Unit and integration tests
├── *.py                 # Main pipeline modules
├── Makefile             # Convenient development commands
├── pyproject.toml       # Project configuration
└── requirements-dev.txt # Development dependencies
```

## Code Style

This project uses:
- **ruff** for linting and formatting
- **basedpyright** for type checking

Configuration is in `pyproject.toml`.

### Adding Dependencies

Add new dependencies to `requirements-dev.txt` for development tools.

## Making Changes

1. Create a new branch for your changes:

```bash
git checkout -b feature/your-feature-name
```

2. Make your changes and ensure all checks pass:

```bash
make lint
make typecheck
make test
```

3. Commit your changes:

```bash
git add .
git commit -m "Description of your changes"
```

4. Push and create a pull request:

```bash
git push origin feature/your-feature-name
```

## Submitting Pull Requests

- Keep PRs focused and small
- Ensure all tests pass
- Update documentation as needed
- Follow the existing code style
- Include a clear description of changes

## Testing

### Adding Tests

Tests are located in the `tests/` directory. Follow these conventions:

- Use Python's built-in `unittest` framework
- Name test files starting with `test_`
- Name test methods starting with `test_`

Example:

```python
import unittest

class TestMyFeature(unittest.TestCase):
    def test_something(self):
        self.assertEqual(1 + 1, 2)
```

Run specific tests:

```bash
python3 -m unittest tests/test_my_module.py
```

### Soak Testing

For stress testing, run repeated pipeline iterations:

```bash
make soak-test
```

## Troubleshooting

### Virtual Environment Issues

If you encounter issues, try cleaning and recreating the venv:

```bash
make clean-all
make setup
```

### Database Issues

The SQLite database is located at `data/daily-blog.db`. To reset:

```bash
rm data/daily-blog.db
```

## Questions?

Feel free to open an issue for questions or problems.
