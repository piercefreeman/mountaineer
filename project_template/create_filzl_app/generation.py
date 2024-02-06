from pydantic import BaseModel
from pathlib import Path
from jinja2 import Template
from create_filzl_app.templates import get_template_path

class ProjectMetadata(BaseModel):
    project_name: str
    author: str
    use_tailwind: bool
    output_path_base: Path

def format_template(name: str, project_metadata: ProjectMetadata) -> tuple[str, Path]:
    """
    Takes in a template path (relative to /templates) and returns the formatted
    template contents and the final path of the file.

    We support:
        - Jinja templating within the file
        - Bracket syntax in filenames, like /path/to/[project_name]/file.txt

    """
    path = get_template_path(name)
    if not path.exists():
        raise FileNotFoundError(f"Template file {path} does not exist")

    metadata_variables = project_metadata.model_dump()

    template = Template(path.read_text())
    content = template.render(metadata_variables)

    output_name = name
    for key, value in metadata_variables.items():
        output_name = output_name.replace(f"[{key}]", value)

    return content, project_metadata.output_path_base / output_name
