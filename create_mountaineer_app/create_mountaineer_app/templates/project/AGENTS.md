# Agent Guide

This project was generated with Mountaineer and Iceaxe. Use these conventions unless a more specific repo-level document overrides them.

## Mountaineer

- Keep the main public entrypoints first in controllers and similar request handlers. Put `render`, route handlers, `@sideeffect`s, and `@passthrough`s before internal helpers.
- Treat one controller as the backend for one frontend page. If multiple pages need the same logic, share that logic through helper functions or a superclass rather than combining pages into one controller.
- Use typed Pydantic models for request and response payloads, and typed `APIException` subclasses for structured API errors.
- After backend controller or schema changes that affect generated frontend types, run `uv run build` before validating the frontend.

### Controller Shape

- `render()` is the SSR entrypoint for initial page data.
- Use `Metadata(...)` from `render()` for page metadata.
- Prefer `Depends(...)` with Mountaineer dependency providers for config, auth, and database access.

### `@sideeffect` vs `@passthrough`

- Use `@sideeffect` for mutations. These trigger a page re-render after execution.
- Use `@passthrough` for read-only queries and utility calls. These return data directly without refreshing page state.
- Prefer `@passthrough` for search, autocomplete, validation, and one-off fetches that do not change persistent state.

## Frontend

- React pages consume server data and actions through `useServer()`.
- Prefer generated link helpers over hardcoded URLs when linking to other controllers.
- Keep frontend code aligned with the controller that owns the page. The page only has direct access to data and actions exposed by that controller.

## Iceaxe

- Use `DatabaseDependencies.get_db_connection` to access the database inside Mountaineer handlers.
- Prefer batched database operations where possible:
  - `await db_connection.insert([obj])`
  - `await db_connection.update([obj])`
  - `await db_connection.delete([obj])`
- Write explicit query expressions with `select(...)` and `where(...)` rather than hiding query logic in ad hoc wrappers.

## Database Workflow

- Bootstrap local schema with `uv run createdb`.
- When a schema change needs a migration, generate a first draft with `uv run migrate generate --message "..."`, then review and edit the generated migration before applying it.
- Apply migrations with `uv run migrate apply`.

## Testing

- Prefer pytest-style tests and reuse fixtures from `conftest.py` before creating new ones.
- For database-backed logic, prefer running against the local Postgres test environment rather than mocking the database layer.
