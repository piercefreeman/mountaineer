# /bin/bash
set -e

# Library linting
echo "Running library linting..."
poetry run ruff format --check filzl
poetry run ruff check filzl
poetry run mypy filzl
