---
name: commit-and-push
description: Run the repo's finalize workflow (uv pytest, pre-commit with per-hook fixes, conventional commit, git push). Use when asked to run tests/lint, fix hook failures, commit changes, or push updates.
---

# Commit And Push

## Overview

Use this workflow to validate changes, fix failures, create a conventional commit, and push.

## Workflow

### 1) Run tests

- Run `uv run pytest`.
- If tests fail, fix the code/tests and re-run until green.
- Tests live in `src/belgie/__test__/`; mirror the source layout.
- Unit tests use the matching file name; integration tests use `_integration` suffix.
- Test functions must be prefixed with `test_`.
- Pytest settings live in `pyproject.toml`.
- If failures are unrelated or require product decisions, stop and ask.

### 2) Run pre-commit and fix hooks

- Run `uv run pre-commit run --all`.
- For each failing hook:
  - Diagnose the root cause and fix it directly.
  - Avoid ignores unless the issue is a true edge case or false positive.
  - Re-run only the failing hook by name: `uv run pre-commit run <hook-name> --all`.
  - If hooks conflict (format vs. lint), resolve the underlying formatting/code issue, then re-run the affected hooks.
- When all hooks pass, run `uv run pre-commit run --all` again to confirm.
- Ruff is the linter; rules are in `pyproject.toml`.
- Type checking uses `ty`. Use specific ignores only when needed, e.g. `# ty: ignore[attr-defined]` with a short reason
  when not obvious.
- Pre-commit configuration is in `.pre-commit-config.yaml`.

### 3) Commit

- Ensure tests and pre-commit pass before committing.
- Use a conventional commit message (single line, lowercase, <72 chars when possible).
- If needed, inspect changes to choose the correct type: `git status -sb`, `git diff --stat`.
- If the changes are already known, skip `git status` and `git diff` and choose the type directly.
- Examples: `feat: added config validator with schema builder`, `fix: corrected validation error message formatting`.
- Avoid multi-line messages or vague subjects.
- Branch names should be kebab-case and prefixed: `feature/`, `bugfix/`, `refactor/`, `docs/`, `test/`.

### 4) Push

- Push with `git push` (autoSetupRemote/autoSetupMerge is configured).
