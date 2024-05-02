from enum import Enum
from pathlib import Path

from jinja2 import Template
from pydantic import BaseModel


class EditorType(Enum):
    VSCODE = "vscode"
    VIM = "vim"
    ZED = "zed"


class ProjectMetadata(BaseModel):
    project_name: str
    author_name: str
    author_email: str
    use_poetry: bool
    use_tailwind: bool
    editor_config: EditorType | None
    project_path: Path

    postgres_password: str = "mysecretpassword"
    postgres_port: int = 5432

    create_stub_files: bool

    # Current version of mountaineer tied to CMA version
    mountaineer_min_version: str

    # Path components to the project's default virtual environment
    # Not set until after the environment is created
    venv_base: str | None = None
    venv_name: str | None = None

    # If specified, will install mountaineer in development mode pointing to a local path
    # This is useful for testing changes to mountaineer itself
    mountaineer_dev_path: Path | None = None


class TemplateOutput(BaseModel):
    content: str
    path: str


def format_template(
    path: Path, base_path: Path, project_metadata: ProjectMetadata
) -> TemplateOutput:
    """
    Takes in a template path (relative to /templates) and returns the formatted
    template contents and the final path of the file.

    We support:
        - Jinja templating within the file
        - Bracket syntax in filenames, like /path/to/[project_name]/file.txt

    """
    if not path.exists():
        raise FileNotFoundError(f"Template file {path} does not exist")

    metadata_variables = project_metadata.model_dump()

    template = Template(path.read_text())
    content = template.render(metadata_variables)

    output_name = str(path.relative_to(base_path))
    for key, value in metadata_variables.items():
        output_name = output_name.replace(f"[{key}]", str(value))

    return TemplateOutput(content=content, path=output_name)
