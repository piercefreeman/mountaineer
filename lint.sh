# /bin/bash
set -e

# Library linting
poetry run ruff format filzl
poetry run ruff check --fix filzl
poetry run mypy filzl

# Example client project linting
(cd my_website && poetry run ruff format my_website)
(cd my_website && poetry run ruff check --fix my_website)
(cd my_website && poetry run mypy my_website)
