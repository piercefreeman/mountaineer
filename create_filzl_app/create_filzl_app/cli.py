import questionary
from click import command, option, secho
from create_filzl_app.external import has_poetry, install_poetry, get_git_user_info
from create_filzl_app.generation import format_template, ProjectMetadata
from create_filzl_app.templates import get_template_path


@command()
@option("--output-path", help="The output path for the bundled files.")
def main(output_path: str | None):
    """
    Create a new Filzl project.

    Most of the configuration is handled interactively. We have a few CLI arguments for rarer options that can configure the installation behavior.

    :param output_path: The output path for the bundled files, if not the current directory.

    """
    input_project_name = questionary.text("Project name [my-project]:").unsafe_ask()
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
                print("Installing poetry...")
                if not install_poetry():
                    # Error installing poetry
                    return

    git_name, git_email = get_git_user_info()
    default_author = f"{git_name} <{git_email}>" if git_name and git_email else None
    input_author = questionary.text(f"Author [{default_author}]").unsafe_ask()

    input_use_tailwind = questionary.confirm(
        "Use Tailwind CSS? [Yes]", default=True
    ).unsafe_ask()

    secho("Creating project...", fg="green")

    template_base = get_template_path("")
    metadata = ProjectMetadata(
        project_name=input_project_name,
        author=input_author,
        use_poetry=input_use_poetry,
        use_tailwind=input_use_tailwind,
    )
    for template_path in template_base.glob("**/*"):
        format_template(str(template_path.relative_to(template_base)), metadata)


if __name__ == "__main__":
    main()
