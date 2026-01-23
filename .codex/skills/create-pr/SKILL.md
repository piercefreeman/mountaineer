---
name: create-pr
description: Create GitHub pull requests with the gh CLI using a conventional-commit title that matches recent commits and a description derived from the diff or a design doc. Use when asked to open a PR, draft a PR, or generate PR titles/bodies from git changes in this repo.
---

# Create Pr

## Overview

Create a PR with `gh pr create` using a conventional-commit title aligned with the latest commit(s) and a body derived
from the design doc or diff.

## Workflow

### 1) Collect change context

- Confirm a clean working tree or commit any staged work.
- Gather high-signal context:
  - `git status -sb`
  - `git log -1 --pretty=%s` for the most recent conventional-commit subject.
  - `git diff --stat` and `git diff` for change scope and details.
  - If the repo has a `main` branch, also compare against it to scope the PR:
    - `git diff --stat main...HEAD` and `git diff main...HEAD`

### 2) Prefer design docs when present

- If any design document is part of the change set, base the PR description primarily on it.
- Locate design docs in diffs or the `design/` directory (e.g., `git diff --name-only | rg '^design/'`).
- If no design doc is present, base the description on the code changes and tests from the diff.

### 3) Build the PR title (conventional commit)

- Use the most recent conventional commit subject as the PR title.
- If multiple commits are present, pick the dominant type/scope and keep the same naming style as the commits.
- Keep it a single-line conventional-commit subject, e.g. `feat(parser): add schema validation`.

### 4) Draft the PR body (design doc or diff)

- Use a short template:
  - Summary: 2–5 bullets describing what changed and why.
  - Testing: list tests run or `Not run (reason)`.
  - Design: link or reference the design doc if present, otherwise omit.

### 5) Create the PR with gh

- Prefer non-interactive creation to ensure title/body accuracy:
  - `gh pr create --title "<conventional-subject>" --body "<body text>"`
- Use flags as needed:
  - `--base` / `--head` to control branches.
  - `--draft` for draft PRs.
  - `--assignee`, `--reviewer`, `--label` if requested.

### 6) Validate output

- Confirm the created PR URL and skim the rendered description for correctness.
