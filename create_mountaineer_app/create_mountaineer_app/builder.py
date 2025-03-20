from pathlib import Path

from click import secho

from create_mountaineer_app.enums import PackageManager
from create_mountaineer_app.environments.base import EnvironmentBase
from create_mountaineer_app.environments.poetry import PoetryEnvironment
from create_mountaineer_app.environments.uv import UvEnvironment
from create_mountaineer_app.environments.venv import VEnvEnvironment
from create_mountaineer_app.external import (
    has_npm,
    npm_install,
)
from create_mountaineer_app.generation import ProjectMetadata, format_template
from create_mountaineer_app.templates import get_template_path

IGNORE_FILES = {"__pycache__", "node_modules"}
ALLOW_HIDDEN_FILES = {
    # A template .env file is explicitly included in our build logic
    ".env",
    ".gitignore",
    ".vimrc",
    ".vscode",
}


def environment_from_metadata(metadata: ProjectMetadata) -> EnvironmentBase:
    if metadata.package_manager == PackageManager.POETRY:
        return PoetryEnvironment()
    elif metadata.package_manager == PackageManager.UV:
        return UvEnvironment()
    else:
        return VEnvEnvironment()


def should_copy_path(root_path: Path, path: Path):
    """
    Determine whether we should copy the template path to our final project.
    We need to ignore certain build-time directories that don't actually
    have code logic.

    - Ignore explicitly ignored files
    - Ignore hidden files and folders

    """
    relative_path = path.relative_to(root_path)

    for part in relative_path.parts:
        if part in IGNORE_FILES:
            return False
        if part.startswith(".") and part not in ALLOW_HIDDEN_FILES:
            return False
    return True


def copy_source_to_project(template_base: Path, metadata: ProjectMetadata):
    template_paths = list(template_base.glob("**/*"))

    if not template_paths:
        all_template_paths = list(get_template_path("").glob("**/*"))
        secho(
            f"No templates found in {template_base}.\n"
            f"Local found: {template_paths}\n"
            f"All found: {all_template_paths}\n"
            "This might indicate an issue with your install or the pypi packaging pipeline.",
            fg="red",
        )
        raise Exception("No templates found.")

    for template_path in template_paths:
        if template_path.is_dir() or not should_copy_path(template_base, template_path):
            continue

        try:
            # Internally, format_template will re-look up the template
            output_bundle = format_template(template_path, template_base, metadata)
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


def build_project(
    metadata: ProjectMetadata,
    install_deps: bool = True,
    mountaineer_wheel: Path | None = None,
):
    template_base = get_template_path("project")

    copy_source_to_project(template_base, metadata)
    secho(f"Project created at {metadata.project_path}", fg="green")

    if install_deps:
        environment = environment_from_metadata(metadata)

        try:
            # If we have a pre-built wheel, configure it in the project dependencies
            if mountaineer_wheel is not None:
                environment.insert_wheel(
                    "mountaineer", mountaineer_wheel, metadata.project_path
                )
                secho("Pre-built mountaineer wheel configured.", fg="green")

            environment.install_project(metadata.project_path)
        except Exception as e:
            secho(f"Error installing python dependencies: {e}", fg="red")

        if has_npm():
            success = npm_install(
                metadata.project_path / metadata.project_name / "views"
            )
            if success:
                secho("npm dependencies installed successfully.", fg="green")
            else:
                secho("npm dependencies installation failed.", fg="red")
        else:
            secho(
                "npm is not installed and is required to install React dependencies.",
                fg="red",
            )

        # Update the metadata now that we have a valid environment
        env_path = Path(environment.get_env_path(metadata.project_path))
        metadata.venv_base = str(env_path.parent)
        metadata.venv_name = env_path.name

        secho("Environment created successfully", fg="green")

    # Now copy the editor-specific files. Some editors don't need a config file so we can
    # optionally skip them if their path is not provided.
    if metadata.editor_config:
        metadata_path = metadata.editor_config.value.path
        if metadata_path:
            editor_template_base = get_template_path("editor_configs") / metadata_path
            copy_source_to_project(editor_template_base, metadata)
            secho(f"Editor config created at {metadata.project_path}", fg="green")
