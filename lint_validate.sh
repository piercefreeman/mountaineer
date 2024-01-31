# /bin/bash
set -e

# Library linting
echo "Running library linting..."
poetry run ruff format filzl
poetry run ruff check --fix filzl
poetry run mypy filzl
