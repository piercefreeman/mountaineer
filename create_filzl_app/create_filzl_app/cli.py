from pathlib import Path

import questionary
from click import command, option, secho

from create_filzl_app.builder import build_project
from create_filzl_app.environments.poetry import PoetryEnvironment
from create_filzl_app.external import (
    get_git_user_info,
)
from create_filzl_app.generation import ProjectMetadata


def prompt_should_use_poetry():
    input_use_poetry = questionary.confirm(
        "Use poetry for dependency management? [Yes]", default=True
    ).unsafe_ask()

    if not input_use_poetry:
        return input_use_poetry

    # Helpful utilities to wrap poetry logic and lifecycle
    poetry_environment = PoetryEnvironment()

    # Determine if the user already has poetry
    if not poetry_environment.has_provider():
        input_install_poetry = questionary.confirm(
            "Poetry is not installed. Install poetry?", default=True
        ).unsafe_ask()
        if input_install_poetry:
            secho("Installing poetry...")
            try:
                poetry_environment.install_provider()
            except Exception as e:
                secho(f"Error installing poetry: {e}", fg="red")
                raise e

    return input_use_poetry


def prompt_author():
    git_name, git_email = get_git_user_info()
    default_author = f"{git_name} <{git_email}>" if git_name and git_email else None
    return questionary.text(f"Author [{default_author}]").unsafe_ask() or str(
        default_author
    )


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
    input_author = prompt_author()
    input_use_poetry = prompt_should_use_poetry()
    input_use_tailwind = questionary.confirm(
        "Use Tailwind CSS? [Yes]", default=True
    ).unsafe_ask()

    secho("\nCreating project...", fg="green")

    project_path = Path(output_path) if output_path else Path.cwd() / input_project_name
    project_path = project_path.resolve()

    metadata = ProjectMetadata(
        project_name=input_project_name.replace(" ", "_").replace("-", "_"),
        author=input_author,
        use_poetry=input_use_poetry,
        use_tailwind=input_use_tailwind,
        project_path=project_path,
    )

    build_project(metadata)


if __name__ == "__main__":
    main()
