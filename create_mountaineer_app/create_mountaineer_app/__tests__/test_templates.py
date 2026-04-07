from pathlib import Path

from create_mountaineer_app.builder import build_project
from create_mountaineer_app.enums import PackageManager
from create_mountaineer_app.generation import ProjectMetadata


def test_project_template_exposes_migrate_script():
    template_path = (
        Path(__file__).parent / ".." / "templates" / "project" / "pyproject.toml"
    ).resolve()

    template_contents = template_path.read_text()

    assert 'migrate = "{{ project_name }}.cli:migrate"' in template_contents


def test_project_template_build_copies_agent_docs(tmp_path: Path):
    metadata = ProjectMetadata(
        project_name="my_project",
        author_name="John Appleseed",
        author_email="test@email.com",
        project_path=tmp_path,
        package_manager=PackageManager.UV,
        use_tailwind=False,
        editor_config=None,
        create_stub_files=False,
        mountaineer_min_version="0.2.5",
        mountaineer_dev_path=None,
    )

    build_project(metadata, install_deps=False)

    assert (tmp_path / "AGENTS.md").exists()
    assert (tmp_path / "CLAUDE.md").read_text() == (
        "Read and follow [AGENTS.md](./AGENTS.md)."
    )


def test_project_template_build_uses_postgres_18_volume_layout(tmp_path: Path):
    metadata = ProjectMetadata(
        project_name="my_project",
        author_name="John Appleseed",
        author_email="test@email.com",
        project_path=tmp_path,
        package_manager=PackageManager.UV,
        use_tailwind=False,
        editor_config=None,
        create_stub_files=False,
        mountaineer_min_version="0.2.5",
        mountaineer_dev_path=None,
    )

    build_project(metadata, install_deps=False)

    docker_compose = (tmp_path / "docker-compose.yml").read_text()

    assert "image: postgres:18" in docker_compose
    assert "my_project_postgres_data:/var/lib/postgresql" in docker_compose
    assert "/var/lib/postgresql/data" not in docker_compose
