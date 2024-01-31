# /bin/bash
set -e

# Library linting
echo "Running library linting..."
poetry run ruff format --check filzl
poetry run ruff check filzl
poetry run mypy filzl

# Example client project linting
echo "Running example client project linting..."
(cd my_website && poetry run ruff format --check my_website)
(cd my_website && poetry run ruff check my_website)
(cd my_website && poetry run mypy my_website)
