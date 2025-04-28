import subprocess
import sys
from itertools import product
from os import environ
from pathlib import Path
from time import sleep
from uuid import uuid4

import pytest
from click import secho
from packaging.requirements import Requirement
from packaging.version import Version
from requests import get

if sys.version_info >= (3, 11):
    from tomllib import loads as toml_loads
else:
    from toml import loads as toml_loads

from create_mountaineer_app.__tests__.common import wait_for_database_to_be_ready
from create_mountaineer_app.builder import (
    build_project,
    environment_from_metadata,
    should_copy_path,
)
from create_mountaineer_app.enums import PackageManager
from create_mountaineer_app.generation import EditorType, ProjectMetadata
from create_mountaineer_app.io import get_free_port
from create_mountaineer_app.templates import get_template_path


@pytest.fixture(scope="session")
def mountaineer_wheel(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """
    Build the mountaineer wheel once per test session and return its path.
    """
    # Create a temporary directory for the wheel
    wheel_dir = tmp_path_factory.mktemp("wheel")

    # Get the main mountaineer package path
    main_mountaineer_path = get_template_path("../../../").resolve()

    # Build the wheel using maturin
    subprocess.run(
        ["uv", "run", "maturin", "build", "--out", str(wheel_dir)],
        cwd=main_mountaineer_path,
        check=True,
    )

    # Find the wheel file - should be the only .whl file in the directory
    wheel_files = list(wheel_dir.glob("*.whl"))
    if not wheel_files:
        raise ValueError("No wheel file was built")

    return wheel_files[0]


@pytest.mark.parametrize(
    "root_path, input_path, expected_copy",
    [
        (
            Path("base"),
            Path("base/myproject/__pycache__/test.pyc"),
            False,
        ),
        (
            Path("base"),
            Path("base/myproject/.git/HEAD"),
            False,
        ),
        (
            Path("base"),
            Path("base/myproject/regular_file.txt"),
            True,
        ),
        (
            # Root paths with hidden files should be excluded from our filtering logic
            # We don't control where installers like pipx place our library
            Path(".cache/pipx/venvs"),
            Path(".cache/pipx/venvs/myproject/regular_file.txt"),
            True,
        ),
    ],
)
def test_copy_path(root_path: Path, input_path: Path, expected_copy: bool):
    assert should_copy_path(root_path, input_path) == expected_copy


@pytest.mark.parametrize(
    "package_manager, use_tailwind, editor_config, create_stub_files",
    list(
        product(
            # Package manager
            [PackageManager.POETRY, PackageManager.UV, PackageManager.VENV],
            # Use tailwind
            [False, True],
            # Editor config
            [None, EditorType.VSCODE, EditorType.VIM, EditorType.ZED],
            # Create stub files
            [False, True],
        )
    ),
)
@pytest.mark.integration_tests
def test_valid_permutations(
    tmpdir: str,
    package_manager: PackageManager,
    use_tailwind: bool,
    editor_config: EditorType | None,
    create_stub_files: bool,
    mountaineer_wheel: Path,
):
    """
    Test that we can create a project with all valid permutations of options.
    """
    new_project_dir = Path(tmpdir) / "my_project"
    main_mountaineer_path = Path(__file__).parent.parent.parent.parent

    # Find an available port for postgres and the webserver
    postgres_port = get_free_port()
    webhost_port = get_free_port()

    metadata = ProjectMetadata(
        project_name="my_project",
        author_name="John Appleseed",
        author_email="test@email.com",
        project_path=new_project_dir,
        package_manager=package_manager,
        use_tailwind=use_tailwind,
        editor_config=editor_config,
        create_stub_files=create_stub_files,
        postgres_port=postgres_port,
        # Stub, not used in template generation since we also have
        # the mountaineer_dev_path
        mountaineer_min_version="0.1.0",
        mountaineer_dev_path=main_mountaineer_path,
    )

    build_project(metadata, mountaineer_wheel=mountaineer_wheel)

    # Launch docker to host the default database
    docker_compose_env = {
        **environ,
        "COMPOSE_PROJECT_NAME": f"test_project-{uuid4()}",
    }
    subprocess.run(
        ["docker", "compose", "up", "-d"],
        cwd=metadata.project_path,
        check=True,
        env=docker_compose_env,
    )

    # Wait until the database is ready
    wait_for_database_to_be_ready(metadata)

    environment = environment_from_metadata(metadata)

    # Make sure the required models are created
    create_db_process = environment.run_command(["createdb"], metadata.project_path)
    output, errors = create_db_process.communicate()
    if create_db_process.returncode != 0:
        if output:
            secho(output.decode("utf-8"), fg="red")
        if errors:
            secho(errors.decode("utf-8"), fg="red")
        raise ValueError("Failed to create database.")

    # Make sure we can build the files without any errors
    build_process = environment.run_command(["build"], metadata.project_path)
    output, errors = build_process.communicate()
    if build_process.returncode != 0:
        if output:
            secho(output.decode("utf-8"), fg="red")
        if errors:
            secho(errors.decode("utf-8"), fg="red")
        raise ValueError("Failed to build project.")

    # Now launch the server in the background
    process = environment.run_command(
        ["runserver", "--port", str(webhost_port)], metadata.project_path
    )

    try:
        # Wait up to 10s for the server to start and be accessible
        max_wait = 10
        while max_wait > 0:
            try:
                response = get(f"http://localhost:{webhost_port}")
                if create_stub_files:
                    if response.ok:
                        break
                else:
                    if response.status_code == 404:
                        break
            except Exception:
                pass
            secho(f"Waiting for server to start (remaining: {max_wait})...")
            sleep(1)
            max_wait -= 1

        assert max_wait > 0, "Server start timed out."

        secho("Test server started successfully", fg="green")

        # Perform the fetch tests
        response = get(f"http://localhost:{webhost_port}")
        if create_stub_files:
            assert response.ok
        else:
            assert response.status_code == 404

        response = get(f"http://localhost:{webhost_port}/not_found")
        assert not response.ok
    finally:
        if process.returncode is None:
            process.terminate()
            process.wait()
            secho("Server shut down...")
        else:
            secho(f"Server exited with code {process.returncode}")

        secho("Shutting down docker...")
        subprocess.run(
            ["docker", "compose", "down"],
            cwd=metadata.project_path,
            check=True,
            env=docker_compose_env,
        )
        secho("Docker shut down successfully.")


@pytest.mark.parametrize(
    "package_manager",
    [PackageManager.POETRY, PackageManager.UV, PackageManager.VENV],
)
def test_build_version_number(package_manager: PackageManager, tmp_path: Path):
    metadata = ProjectMetadata(
        project_name="my_project",
        author_name="John Appleseed",
        author_email="test@email.com",
        project_path=tmp_path,
        package_manager=package_manager,
        use_tailwind=False,
        editor_config=None,
        create_stub_files=False,
        mountaineer_min_version="0.2.5",
        mountaineer_dev_path=None,
    )
    build_project(metadata, install_deps=False)

    pyproject_contents = (tmp_path / "pyproject.toml").read_text()
    package_requirements = toml_loads(pyproject_contents)

    version = package_requirements["project"]["dependencies"][0]
    req = Requirement(version)
    assert req.specifier.contains(Version("0.2.5"))
