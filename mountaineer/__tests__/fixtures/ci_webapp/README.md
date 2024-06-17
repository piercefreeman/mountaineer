# ci-webapp

An example webapp, built with mountaineer. This is intended for use by CI only, to test various edge cases that are more easily served by a fully functioning webapp.

## Getting Started

We link to the local version of mountaineer in `pyproject.toml`. On the first install it should fetch dependencies with poetry and then build the rust components with maturin.

```bash
poetry install
(cd my_website/views && npm install)

poetry run runserver
```

If you're doing concurrent development in the main mountaineer codebase, you will have to manually restart the `runserver` command. Python changes in the main mountaineer package will be picked up - but you'll have to rebuild the rust artifacts with maturin. See the main README for instructions on how to do this.

Changes in the my_website codebase should be automatically picked up.
