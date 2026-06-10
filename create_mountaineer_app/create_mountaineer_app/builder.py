from pathlib import Path

from create_mountaineer_app import ui
from create_mountaineer_app.enums import PackageManager
from create_mountaineer_app.environments.base import EnvironmentBase
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
    ".dockerignore",
    ".gitignore",
    ".vimrc",
    ".vscode",
}


def environment_from_metadata(metadata: ProjectMetadata) -> EnvironmentBase:
    if metadata.package_manager == PackageManager.UV:
        return UvEnvironment()

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


def copy_source_to_project(
    template_base: Path, metadata: ProjectMetadata, label: str = "Writing files"
) -> tuple[int, list[str]]:
    template_paths = list(template_base.glob("**/*"))

    if not template_paths:
        all_template_paths = list(get_template_path("").glob("**/*"))
        ui.error(
            f"No templates found in {template_base}.\n"
            f"Local found: {template_paths}\n"
            f"All found: {all_template_paths}\n"
            "This might indicate an issue with your install or the pypi packaging pipeline.",
        )
        raise Exception("No templates found.")

    created_files = 0
    skipped_empty_files: list[str] = []

    with ui.status(label):
        for template_path in template_paths:
            if template_path.is_dir() or not should_copy_path(
                template_base, template_path
            ):
                continue

            try:
                # Internally, format_template will re-look up the template
                output_bundle = format_template(template_path, template_base, metadata)
            except Exception as e:
                ui.error(f"Error formatting {template_path}: {e}")
                raise e

            if not output_bundle.content.strip():
                skipped_empty_files.append(output_bundle.path)
                continue

            full_output = metadata.project_path / output_bundle.path
            full_output.parent.mkdir(parents=True, exist_ok=True)
            full_output.write_text(output_bundle.content)
            created_files += 1

    ui.success(f"Wrote {created_files} files")
    if skipped_empty_files:
        ui.warning(f"Skipped {len(skipped_empty_files)} empty templates")

    return created_files, skipped_empty_files


def build_project(
    metadata: ProjectMetadata,
    install_deps: bool = True,
    mountaineer_wheel: Path | None = None,
):
    template_base = get_template_path("project")

    ui.section("Creating project")
    ui.detail("Name", metadata.project_name)
    ui.detail("Location", metadata.project_path)
    ui.detail("Package manager", metadata.package_manager.value)

    copy_source_to_project(template_base, metadata, "Writing project files")
    ui.success("Project created")

    if install_deps:
        environment = environment_from_metadata(metadata)

        ui.section("Installing Python dependencies")
        # If we have a pre-built wheel, configure it in the project dependencies
        if mountaineer_wheel is not None:
            environment.insert_wheel(
                "mountaineer", mountaineer_wheel, metadata.project_path
            )
            ui.success("Pre-built mountaineer wheel configured")

        environment.install_project(metadata.project_path)

        if has_npm():
            ui.section("Installing frontend dependencies")
            success = npm_install(
                metadata.project_path / metadata.project_name / "views"
            )
            if success:
                ui.success("npm dependencies installed")
            else:
                ui.error("npm dependencies installation failed")
        else:
            ui.error(
                "npm is not installed and is required to install React dependencies.",
            )

        # Update the metadata now that we have a valid environment
        env_path = Path(environment.get_env_path(metadata.project_path))
        metadata.venv_base = str(env_path.parent)
        metadata.venv_name = env_path.name

        ui.success("Environment created successfully")

    # Now copy the editor-specific files. Some editors don't need a config file so we can
    # optionally skip them if their path is not provided.
    if metadata.editor_config:
        metadata_path = metadata.editor_config.value.path
        if metadata_path:
            ui.section("Configuring editor")
            editor_template_base = get_template_path("editor_configs") / metadata_path
            copy_source_to_project(
                editor_template_base, metadata, "Writing editor files"
            )
            ui.success("Editor config created")
