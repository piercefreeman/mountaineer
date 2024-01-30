# my-website

An example webapp, built with filzl.

## Getting Started

We link to the local version of filzl in `pyproject.toml`. On the first install it should fetch dependencies with poetry and then build the rust components with maturin.

```bash
poetry install
poetry run runserver
```

If you're doing concurrent development in the main filzl codebase, you will have to manually restart the `runserver` command. Python changes in the main filzl package will be picked up - but you'll have to rebuild the rust artifacts with maturin. See the main README for instructions on how to do this.

Changes in the my_website codebase should be automatically picked up.
