from pathlib import Path

from click import secho

from create_mountaineer_app.environments.base import EnvironmentBase
from create_mountaineer_app.environments.poetry import PoetryEnvironment
from create_mountaineer_app.environments.venv import VEnvEnvironment
from create_mountaineer_app.external import (
    has_npm,
    npm_install,
)
from create_mountaineer_app.generation import ProjectMetadata, format_template
from create_mountaineer_app.templates import get_template_path

IGNORE_FILES = {"__pycache__", "node_modules"}
ALLOW_HIDDEN_FILES = {".env"}


def environment_from_metadata(metadata: ProjectMetadata) -> EnvironmentBase:
    if metadata.use_poetry:
        return PoetryEnvironment()
    else:
        return VEnvEnvironment()


def should_copy_path(path: Path):
    """
    Determine whether we should copy the template path to our final project.
    We need to ignore certain build-time directories that don't actually
    have code logic.

    - Ignore explicitly ignored files
    - Ignore hidden files and folders

    """
    for part in path.parts:
        if part in IGNORE_FILES:
            return False
        if part.startswith(".") and part not in ALLOW_HIDDEN_FILES:
            return False
    return True


def build_project(metadata: ProjectMetadata):
    template_base = get_template_path("project")

    for template_path in template_base.glob("**/*"):
        if template_path.is_dir() or not should_copy_path(template_path):
            continue

        # Internally, format_template will re-look up the template. Convert the full glob path into a relative template path.
        template_name = str(template_path.relative_to(template_base))
        try:
            output_bundle = format_template(template_name, metadata)
        except Exception as e:
            secho(f"Error formatting {template_path}: {e}", fg="red")
            raise e

        if not output_bundle.content.strip():
            secho(
                f"No content detected in {output_bundle.path}, skipping...", fg="yellow"
            )
            continue

        secho(f"Creating {output_bundle.path}")
        full_output = metadata.project_path / output_bundle.path
        full_output.parent.mkdir(parents=True, exist_ok=True)
        full_output.write_text(output_bundle.content)

    secho(f"Project created at {metadata.project_path}", fg="green")

    environment = environment_from_metadata(metadata)

    try:
        environment.install_project(metadata.project_path)
    except Exception as e:
        secho(f"Error installing python dependencies: {e}", fg="red")

    if has_npm():
        npm_install(metadata.project_path / metadata.project_name / "views")
    else:
        secho(
            "npm is not installed and is required to install React dependencies.",
            fg="red",
        )
