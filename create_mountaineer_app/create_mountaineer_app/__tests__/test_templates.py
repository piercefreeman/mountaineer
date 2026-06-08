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


def test_project_template_readme_mentions_renewing_node_modules_volume():
    template_path = (
        Path(__file__).parent / ".." / "templates" / "project" / "README.md"
    ).resolve()

    template_contents = template_path.read_text()

    assert "docker compose up -d --build --renew-anon-volumes" in template_contents
    assert "docker compose down -v" in template_contents
    assert "anonymous Docker volume" in template_contents


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


def test_project_template_build_copies_dockerignore(tmp_path: Path):
    metadata = ProjectMetadata(
        project_name="my_project",
        author_name="John Appleseed",
        author_email="test@email.com",
        project_path=tmp_path,
        package_manager=PackageManager.UV,
        use_tailwind=True,
        editor_config=None,
        create_stub_files=False,
        mountaineer_min_version="0.2.5",
        mountaineer_dev_path=None,
    )

    build_project(metadata, install_deps=False)

    assert (tmp_path / ".dockerignore").read_text().rstrip() == (
        (Path(__file__).parent / ".." / "templates" / "project" / ".dockerignore")
        .resolve()
        .read_text()
        .rstrip()
    )


def test_project_template_build_uses_node_20_for_docker_builds(tmp_path: Path):
    metadata = ProjectMetadata(
        project_name="my_project",
        author_name="John Appleseed",
        author_email="test@email.com",
        project_path=tmp_path,
        package_manager=PackageManager.UV,
        use_tailwind=True,
        editor_config=None,
        create_stub_files=False,
        mountaineer_min_version="0.2.5",
        mountaineer_dev_path=None,
    )

    build_project(metadata, install_deps=False)

    dockerfile = (tmp_path / "Dockerfile").read_text()
    dockerfile_local = (tmp_path / "Dockerfile.local").read_text()

    for contents in (dockerfile, dockerfile_local):
        assert "FROM node:20-bookworm-slim" in contents
        assert "node-runtime" in contents
        assert (
            "COPY --from=node-runtime /usr/local/bin/node /usr/local/bin/node"
            in contents
        )
        assert (
            "COPY --from=node-runtime /usr/local/lib/node_modules /usr/local/lib/node_modules"
            in contents
        )
        assert (
            "ln -sf ../lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm"
            in contents
        )

    assert "apt-get install -y --no-install-recommends nodejs" not in dockerfile
    assert (
        "apt-get install -y --no-install-recommends nodejs npm" not in dockerfile_local
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


def test_project_template_build_adds_database_setup_guard(tmp_path: Path):
    metadata = ProjectMetadata(
        project_name="my_project",
        author_name="John Appleseed",
        author_email="test@email.com",
        project_path=tmp_path,
        package_manager=PackageManager.UV,
        use_tailwind=True,
        editor_config=None,
        create_stub_files=True,
        mountaineer_min_version="0.2.5",
        mountaineer_dev_path=None,
    )

    build_project(metadata, install_deps=False)

    home_controller = (tmp_path / "my_project" / "controllers" / "home.py").read_text()
    home_view = (
        tmp_path / "my_project" / "views" / "app" / "home" / "page.tsx"
    ).read_text()
    database_setup_helper = (tmp_path / "my_project" / "database_setup.py").read_text()
    database_setup_view = (
        tmp_path
        / "my_project"
        / "views"
        / "app"
        / "_common"
        / "database-setup-page.tsx"
    ).read_text()

    assert "database_setup_required" in home_controller
    assert "get_database_setup_required" in home_controller
    assert "DatabaseSetupPage" in home_view
    assert 'CREATEDB_COMMAND = "uv run createdb"' in database_setup_helper
    assert "Then refresh this page." in database_setup_view
