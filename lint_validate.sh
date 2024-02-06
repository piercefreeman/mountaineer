# /bin/bash
set -e

# Library linting
echo "Running library linting..."
poetry run ruff format --check filzl
poetry run ruff check filzl
poetry run mypy filzl

# create-filzl-app linting
echo "Running create_filzl_app linting..."
(cd create_filzl_app && poetry run ruff format --check create_filzl_app)
(cd create_filzl_app && poetry run ruff check create_filzl_app)
(cd create_filzl_app && poetry run mypy create_filzl_app)
