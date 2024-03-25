from pathlib import Path

from create_mountaineer_app.generation import ProjectMetadata, format_template
from create_mountaineer_app.templates import get_template_path


def test_path_url_replacement():
    metadata = ProjectMetadata(
        project_name="TEST_PROJECT_NAME",
        author_name="TEST_AUTHOR",
        author_email="TEST_EMAIL",
        use_tailwind=True,
        use_poetry=True,
        editor_config=None,
        create_stub_files=True,
        project_path=Path("fake-path"),
        mountaineer_min_version="0.1.0",
        mountaineer_dev_path=None,
    )
    project_template_base = get_template_path("project")
    bundle = format_template(
        project_template_base / "[project_name]/app.py", project_template_base, metadata
    )
    assert bundle.path == "TEST_PROJECT_NAME/app.py"
