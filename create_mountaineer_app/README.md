![Mountaineer Header](https://raw.githubusercontent.com/piercefreeman/mountaineer/main/media/header.png)

# Project Template

CLI to setup a basic scaffolding for mountaineer. This provides a simple base project that can be generated via UV.

```bash
uv run create-mountaineer-app
```

## Installing UV

UV is a fast Python package installer and resolver, written in Rust. Follow their [install guide](https://github.com/astral-sh/uv#installation) to get started.

## Development

If you're making frequent changes in development, you can create a fresh project directory:

```bash
rm -rf test-project && uv run create-mountaineer-app --output-path test-project --mountaineer-dev-path ../
```

For local development on the CLI itself, install in editable mode:

```bash
uv pip install -e .
```
