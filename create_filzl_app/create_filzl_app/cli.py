from pathlib import Path

import questionary
from click import command, option, secho

from create_filzl_app.external import (
    get_git_user_info,
    has_npm,
    has_poetry,
    install_poetry,
    npm_install,
    poetry_install,
)
from create_filzl_app.generation import ProjectMetadata, format_template
from create_filzl_app.templates import get_template_path

IGNORE_FILES = {"__pycache__", "node_modules"}


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
        if part.startswith("."):
            return False
    return True


@command()
@option("--output-path", help="The output path for the bundled files.")
def main(output_path: str | None):
    """
    Create a new Filzl project.

    Most of the configuration is handled interactively. We have a few CLI arguments for rarer options that can configure the installation behavior.

    :param output_path: The output path for the bundled files, if not the current directory.

    """
    input_project_name = (
        questionary.text("Project name [my-project]:").unsafe_ask() or "my-project"
    )
    input_use_poetry = questionary.confirm(
        "Use poetry for dependency management? [Yes]", default=True
    ).unsafe_ask()

    if input_use_poetry:
        # Determine if the user already has poetry
        if not has_poetry():
            input_install_poetry = questionary.confirm(
                "Poetry is not installed. Install poetry?", default=True
            ).unsafe_ask()
            if input_install_poetry:
                secho("Installing poetry...")
                if not install_poetry():
                    # Error installing poetry
                    return

    git_name, git_email = get_git_user_info()
    default_author = f"{git_name} <{git_email}>" if git_name and git_email else None
    input_author = questionary.text(f"Author [{default_author}]").unsafe_ask() or str(
        default_author
    )

    input_use_tailwind = questionary.confirm(
        "Use Tailwind CSS? [Yes]", default=True
    ).unsafe_ask()

    secho("\nCreating project...", fg="green")

    project_path = Path(output_path) if output_path else Path.cwd() / input_project_name
    project_path = project_path.resolve()
    template_base = get_template_path("project")

    metadata = ProjectMetadata(
        project_name=input_project_name.replace(" ", "_").replace("-", "_"),
        author=input_author,
        use_poetry=input_use_poetry,
        use_tailwind=input_use_tailwind,
    )
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
        full_output = project_path / output_bundle.path
        full_output.parent.mkdir(parents=True, exist_ok=True)
        full_output.write_text(output_bundle.content)

    secho(f"Project created at {project_path}", fg="green")

    if input_use_poetry:
        poetry_install(project_path)

    if has_npm():
        npm_install(project_path / metadata.project_name / "views")
    else:
        secho(
            "npm is not installed and is required to install React dependencies.",
            fg="red",
        )


if __name__ == "__main__":
    main()
