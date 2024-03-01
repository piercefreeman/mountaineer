import subprocess
from itertools import product
from os import environ
from pathlib import Path
from time import sleep
from uuid import uuid4

import pytest
from click import secho
from requests import get

from create_mountaineer_app.__tests__.common import wait_for_database_to_be_ready
from create_mountaineer_app.builder import (
    build_project,
    environment_from_metadata,
    should_copy_path,
)
from create_mountaineer_app.generation import ProjectMetadata
from create_mountaineer_app.io import get_free_port
from create_mountaineer_app.templates import get_template_path


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
    "use_poetry, use_tailwind, editor_config, create_stub_files",
    list(
        product(
            # Use poetry
            [False, True],
            # Use tailwind
            [False, True],
            # Editor config
            ["no", "vscode", "vim"],
            # Create stub files
            [False, True],
        )
    ),
)
@pytest.mark.integration_tests
def test_valid_permutations(
    tmpdir: str,
    use_poetry: bool,
    use_tailwind: bool,
    editor_config: str,
    create_stub_files: bool,
):
    """
    Ensures that regardless of the input parameters
    used to generate our new project, it will successfully
    run and return the expected endpoints.

    """
    new_project_dir = Path(tmpdir) / str(uuid4())
    new_project_dir.mkdir()

    # Assume the create-mountaineer-app project is in the same directory as the
    # main mountaineer package. We use a slight hack here assuming that our file
    # directory is oriented like "mountaineer/create_mountaineer_app/create_mountaineer_app/templates"
    # main package.
    main_mountaineer_path = get_template_path("../../../").resolve()

    # Verify this is pointing to where we expect
    if not (main_mountaineer_path / "pyproject.toml").exists():
        raise ValueError("Unable to find the main mountaineer package.")

    app_test_port = get_free_port()
    postgres_port = get_free_port()
    secho(f"Found free port for test server: {app_test_port}", fg="green")

    metadata = ProjectMetadata(
        project_name="my_project",
        author_name="John Appleseed",
        author_email="test@email.com",
        project_path=new_project_dir,
        use_poetry=use_poetry,
        use_tailwind=use_tailwind,
        editor_config=editor_config,
        create_stub_files=create_stub_files,
        postgres_port=postgres_port,
        mountaineer_dev_path=main_mountaineer_path,
    )

    build_project(metadata)

    # Launch docker to host the default database
    docker_compose_env = {
        **environ,
        "COMPOSE_PROJECT_NAME": f"test_project-{uuid4()}",
    }
    subprocess.run(
        ["docker-compose", "up", "-d"],
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
        secho(output.decode("utf-8"), fg="red")
        secho(errors.decode("utf-8"), fg="red")
        raise ValueError("Failed to create database.")

    # Make sure we can build the files without any errors
    build_process = environment.run_command(["build"], metadata.project_path)
    output, errors = build_process.communicate()
    if build_process.returncode != 0:
        secho(output.decode("utf-8"), fg="red")
        secho(errors.decode("utf-8"), fg="red")
        raise ValueError("Failed to build project.")

    # Now launch the server in the background
    process = environment.run_command(
        ["runserver", "--port", str(app_test_port)], metadata.project_path
    )

    try:
        # Wait up to 10s for the server to start and be accessible
        max_wait = 10
        while max_wait > 0:
            try:
                response = get(f"http://localhost:{app_test_port}")
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
        response = get(f"http://localhost:{app_test_port}")
        if create_stub_files:
            assert response.ok
        else:
            assert response.status_code == 404

        response = get(f"http://localhost:{app_test_port}/not_found")
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
            ["docker-compose", "down"],
            cwd=metadata.project_path,
            check=True,
            env=docker_compose_env,
        )
        secho("Docker shut down successfully.")
