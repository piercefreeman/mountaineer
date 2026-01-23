# Agent Instructions

## Tooling

### Package management

- The package manger for the project is [uv](https://docs.astral.sh/uv/)
- Make `uv add` for core dependencies, `uv add --dev` for developer dependencies, and add optional features to groups
- It is also possible to remove packages using `uv remove`

## Testing

- The project uses `pytest` for testing
- Test files are located in the `src/belgie/__test__/` directory
- Test files should mirror the folder structure and use corresponding file names
  - Test file with matching name contains unit tests
  - Integration tests use `_integration` suffix
  - Example: `module_x/test_corresponding_file.py` (unit tests)
  - Example: `module_x/test_corresponding_file_integration.py` (integration tests)
- Test functions should be prefixed with `test_`
- Mark integration tests with `@pytest.mark.integration` and run them via `uv run pytest -m "integration"` (or
  `-m "not integration"` for unit-only).
- Run tests using `uv run pytest`
- The `pytest` settings can be found in the `pyproject.toml`

## Linting

- The project relies on [ruff](https://docs.astral.sh/ruff/) for linting
- The enabled / disabled rules rules can be found in the `pyproject.toml`
- If there is a linter error / warning, try to fix it
- If an error is an edge cases (i.e. requires significant work to fix or is impossible) - add a rule specific ignore

## Type Checking

- The project uses [ty](https://docs.astral.sh/ty/) for type checking
- Similar to the linter, if there is an error that is invalid or extraneous use rule specific suppression
  - For example: `# ty: ignore[unsupported-operator]`
- **When to use `# ty: ignore`**:
  - Type checker reports false positives due to dynamic code
  - Third-party library has incorrect or missing type stubs
  - Valid code that the type checker cannot understand (e.g., certain metaclass patterns)
  - Edge cases where adding correct types would make code significantly more complex
- **Best practices for type ignore comments**:
  - Always use specific error codes: `# ty: ignore[error-code]` (not bare `# ty: ignore`)
  - Add inline explanation when the reason isn't obvious:
    `# ty: ignore[attr-defined]  # Dynamic attribute from metaclass`
  - Consider if the code can be refactored to avoid the ignore
  - Common error codes:
    - `[attr-defined]` - Attribute doesn't exist on type
    - `[arg-type]` - Argument has wrong type
    - `[return-value]` - Return type doesn't match annotation
    - `[assignment]` - Assignment target incompatible with value
    - `[union-attr]` - Attribute only on some union members
    - `[index]` - Invalid index operation

## Pre-Commit Hooks

- The project relies on `pre-commit` to handle the linting, type checking, etc. automatically
- It is configured in the `.pre-commit-config.yaml`

## Conventions

### Git

- Before you commit code, **make sure** you have added comprehensive test cases
- **Commit messages**:
  - Follow the [conventional commits](https://www.conventionalcommits.org/en/v1.0.0/) format
  - **Must be a single line** - no multi-line messages or bullet points
  - Keep it short and concise (under 72 characters when possible)
  - Use all lowercase characters
  - Avoid special characters
  - Focus on **what** changed, not the detailed **how** or **why**
  - Examples of good commit messages:
    - `feat: added config validator with schema builder`
    - `fix: corrected validation error message formatting`
    - `refactor: simplified schema field definition logic`
    - `docs: updated design template with usage examples`
    - `test: added edge case tests for range validator`
  - Examples of bad commit messages:
    - ❌ Multi-line messages with detailed explanations
    - ❌ `feat: added config validator\n\n- Added schema builder\n- Added validators`
    - ❌ `Fixed stuff` (too vague, no type prefix)
    - ❌ `FEAT: Added Config Validator` (not lowercase)
- **Branch naming conventions**:
  - Use descriptive, kebab-case branch names
  - Prefix branches by type: `feature/`, `bugfix/`, `refactor/`, `docs/`, `test/`
  - Include brief description of the work
  - Examples:
    - `feature/config-validator`
    - `bugfix/fix-validation-error-messages`
    - `refactor/simplify-schema-builder`
    - `docs/update-readme-examples`

### Python

- The targets python versions greater than or equal to 3.12
- Given the project targets a more modern python, use functionality such as:
  - The walrus operator (`:=`)
  - Prefer keyword arguments (strict assignment) over positional calls for clarity and linting, e.g., `my_func(a=1)`
    instead of `my_func(1)`
  - Modern type hints (`dict`)
  - Type parameters `class MyClass[T: MyParent]: ...`
  - The `Self` type for return types (`from typing import Self`)
- Type annotations:
  - **Do not** annotate `self` parameters - the type is implicit
  - Use `Self` for return types when returning the instance
  - Example: `def add_item(self, item: str) -> Self: ...` (note: no type on `self`)
- Classes and data structures:
  - Use `@dataclass` (from `dataclasses`) instead of manually defining `__init__` for data-holding classes
  - Consider using `slots=True` for memory efficiency and attribute access protection
  - Use `kw_only=True` to require keyword arguments for better readability at call sites
  - Use `frozen=True` for immutable data structures
  - Example: `@dataclass(slots=True, kw_only=True, frozen=True)`
  - **When NOT to use dataclass**:
    - Inheriting from non-dataclass parents (can cause MRO and initialization issues)
    - Need for `__new__` method (for singleton patterns, custom object creation)
    - Complex property logic with getters/setters that transform data
    - Need for `__init_subclass__` or metaclass customization
    - Classes with significant behavior/methods (prefer traditional classes for these)
  - **When to use dataclass**:
    - Simple data containers with minimal logic
    - Configuration objects, DTOs (Data Transfer Objects), result types
    - Immutable value objects (use `frozen=True`)
    - When you want automatic `__eq__`, `__repr__`, `__hash__` implementations
- Prefer importing using `from x import y` instead of `import x`
- Import local modules using the full path (ex: `from my_project.my_module import MyClass`)
- **Don't use** docstrings, instead add inline comments only in places where there is complex or easily breakable logic
- For type aliases, prefer Python's modern syntax: `type MyAlias = SomeType` (PEP 695 style), especially in new code.
- URL construction:
  - Use `urllib.parse` methods for URL manipulation (don't use string concatenation or f-strings for query params)
  - Use `urlencode()` for query parameters
  - Use `urlparse()` and `urlunparse()` for URL composition
  - Example: `urlunparse((parsed.scheme, parsed.netloc, parsed.path, "", urlencode(params), ""))`
  - This ensures proper encoding and avoids common URL injection vulnerabilities

### Style

- Default to keyword arguments for function calls when parameters are known (`call(x=val, y=other)`), which aids
  readability and static analysis.
- Prefer keyword arguments (strict assignment) over positional calls for clarity and lintability, e.g., write
  `my_func(a=1)` instead of `my_func(1)` whenever feasible.
