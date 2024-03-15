![Mountaineer Header](https://raw.githubusercontent.com/piercefreeman/mountaineer/main/docs/media/header.png)

# Project Template

CLI to setup a basic scaffolding for mountaineer. This provides a simple base project that can be generated via pipx.

```bash
pipx run create-mountaineer-app
```

## Installing pipx

pipx is similar in nature to npx, except it's not installed by default alongside npm. Follow their [install guide](https://pipx.pypa.io/stable/installation/) to get started.

Once pipx is installed, you can call the latest create-mountaineer-app logic without installing the package globally.

## Development

To work on `create-mountaineer-app`, we use poetry to manage local dependencies. Note this is only required if you're hacking on this CLI, not if you just want to run it.

```bash
poetry install
```

If you're making frequent changes in development, you'll often want to create a fully fresh project directory in the CLI:

```bash
poetry install
rm -rf test-project && poetry run create-mountaineer-app --output-path test-project --mountaineer-dev-path ../
```

### Client Poetry Installation

If you want to test the full poetry install, you can temporarily uninstall poetry and validate it's installed by this installer:

```bash
curl -sSL https://install.python-poetry.org | python3 - --uninstall
curl -sSL https://install.python-poetry.org | POETRY_UNINSTALL=1 python3 -
```

Then, run `create-mountaineer-app` via a virtualenv:

```bash
python -m venv create_app_venv
source create_app_venv/bin/activate

pip install -e .
python create_mountaineer_app/cli.py
```
