from pathlib import Path

from jinja2 import Template
from pydantic import BaseModel

from create_mountaineer_app.templates import get_template_path


class ProjectMetadata(BaseModel):
    project_name: str
    author_name: str
    author_email: str
    use_poetry: bool
    use_tailwind: bool
    editor_config: str
    project_path: Path

    postgres_password: str = "mysecretpassword"
    postgres_port: int = 5432

    create_stub_files: bool

    # If specified, will install mountaineer in development mode pointing to a local path
    # This is useful for testing changes to mountaineer itself
    mountaineer_dev_path: Path | None = None


class TemplateOutput(BaseModel):
    content: str
    path: str


def format_template(name: str, project_metadata: ProjectMetadata) -> TemplateOutput:
    """
    Takes in a template path (relative to /templates) and returns the formatted
    template contents and the final path of the file.

    We support:
        - Jinja templating within the file
        - Bracket syntax in filenames, like /path/to/[project_name]/file.txt

    """
    path = get_template_path("project") / name
    if not path.exists():
        raise FileNotFoundError(f"Template file {path} does not exist")

    metadata_variables = project_metadata.model_dump()

    template = Template(path.read_text())
    content = template.render(metadata_variables)

    output_name = name
    for key, value in metadata_variables.items():
        output_name = output_name.replace(f"[{key}]", str(value))

    return TemplateOutput(content=content, path=output_name)
