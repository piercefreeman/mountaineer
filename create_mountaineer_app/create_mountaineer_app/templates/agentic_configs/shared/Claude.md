# Claude Project Context

This repository is a generated Mountaineer app named `{{project_name}}`.

## What This App Uses
- Backend: Mountaineer/FastAPI (`{{project_name}}/`)
- Database: PostgreSQL with Iceaxe models/migrations
- Frontend: React + TypeScript (`{{project_name}}/views`)

## Important Paths
- Controllers: `{{project_name}}/controllers/`
- Data models: `{{project_name}}/models/`
- App setup: `{{project_name}}/app.py`, `{{project_name}}/main.py`
- Environment config: `.env`
- CLI entrypoints: `{{project_name}}/cli.py`

## First-Run Checklist
- Start DB: `docker compose up -d postgres`
- Create schema (preferred migration flow):
{% if package_manager == 'poetry' %}
  - `poetry run migrate generate --message init`
  - `poetry run migrate apply`
{% elif package_manager == 'uv' %}
  - `uv run migrate generate --message init`
  - `uv run migrate apply`
{% else %}
  - `source venv/bin/activate`
  - `migrate generate --message init`
  - `migrate apply`
{% endif %}
- Run app:
{% if package_manager == 'poetry' %}
  - `poetry run runserver`
{% elif package_manager == 'uv' %}
  - `uv run runserver`
{% else %}
  - `runserver`
{% endif %}

## Working Rules for Claude
- Keep edits minimal, local, and testable.
- Use `rg` for search and keep naming/style consistent.
- Do not use destructive git commands.
- If schema changes, include migration generation/application steps.
- Prefer fixing root causes over quick patches.

## Validation Commands
{% if package_manager == 'poetry' %}
- `poetry run pytest`
- `poetry run ruff check .`
{% elif package_manager == 'uv' %}
- `uv run pytest`
- `uv run ruff check .`
{% else %}
- `pytest`
- `ruff check .`
{% endif %}
