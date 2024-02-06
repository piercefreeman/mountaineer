# Project Template

CLI to setup a basic scaffolding for filzl. Provides a simple base project that can be executed via pipx. pipx is similar in nature to npx, except it's not installed by default alongside npm. Follow their [install guide](https://pipx.pypa.io/stable/installation/) to get started.

Once pipx is installed, you can call the latest create-filzl-app logic without installing the package globally.

```bash
pipx run create-filzl-app new
```

## Development

We use poetry to manage local dependencies:

```bash
poetry install
poetry run new
```

### Modifying the Template

For convenience when modifying the template locally, we let you edit templates in non-jinja format and then will apply changes.

```bash
$ poetry run start-template-dev

Customize your project at: XXX.
```

Then, just interrupt this session (Control-C) once you're finished editing. We will ask you to review the changes and whether you'd like to apply them to the original jinja template.

If changes are wrapped in jinja blocks, you might have to make manual modifications to the raw template.

### Client Poetry Installation

If you want to test the full poetry install, you can temporarily uninstall poetry and validate it's installed by this installer:

```bash
curl -sSL https://install.python-poetry.org | python3 - --uninstall
curl -sSL https://install.python-poetry.org | POETRY_UNINSTALL=1 python3 -
```

Then, run `create-filzl-app` via a virtualenv:

```bash
python -m venv create_app_venv
source create_app_venv/bin/activate

pip install -e .
python create_filzl_app/cli.py
```
