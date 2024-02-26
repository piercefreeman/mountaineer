import subprocess
from itertools import product
from pathlib import Path
from time import sleep

import pytest
from click import secho
from requests import get

from create_mountaineer_app.builder import (
    build_project,
    environment_from_metadata,
    should_copy_path,
)
from create_mountaineer_app.generation import ProjectMetadata
from create_mountaineer_app.io import get_free_port
from create_mountaineer_app.templates import get_template_path


@pytest.mark.parametrize(
    "input_path, expected_copy",
    [
        (
            Path("myproject/__pycache__/test.pyc"),
            False,
        ),
        (
            Path("myproject/.gitignore"),
            False,
        ),
        (
            Path("myproject/.git/HEAD"),
            False,
        ),
        (
            Path("myproject/regular_file.txt"),
            True,
        ),
    ],
)
def test_copy_path(input_path: Path, expected_copy: bool):
    assert should_copy_path(input_path) == expected_copy


@pytest.mark.parametrize(
    "use_poetry, use_tailwind",
    product(
        # Use poetry
        [False, True],
        # Use tailwind
        [False, True],
    ),
)
@pytest.mark.integration_tests
def test_valid_permutations(
    tmpdir: str,
    use_poetry: bool,
    use_tailwind: bool,
):
    """
    Ensures that regardless of the input parameters
    used to generate our new project, it will successfully
    run and return the expected endpoints.

    """
    # Assume the create-mountaineer-app project is in the same directory as the
    # main mountaineer package. We use a slight hack here assuming that our file
    # directory is oriented like "mountaineer/create_mountaineer_app/create_mountaineer_app/templates"
    # main package.
    main_mountaineer_path = get_template_path("../../../").resolve()

    # Verify this is pointing to where we expect
    if not (main_mountaineer_path / "pyproject.toml").exists():
        raise ValueError("Unable to find the main mountaineer package.")

    metadata = ProjectMetadata(
        project_name="my_project",
        author_name="John Appleseed",
        author_email="test@email.com",
        project_path=Path(tmpdir),
        use_poetry=use_poetry,
        use_tailwind=use_tailwind,
        mountaineer_dev_path=main_mountaineer_path,
    )

    build_project(metadata)

    app_test_port = get_free_port()
    secho(f"Found free port for test server: {app_test_port}", fg="green")

    # Launch docker to host the default database
    subprocess.run(
        ["docker-compose", "up", "-d"], cwd=metadata.project_path, check=True
    )

    environment = environment_from_metadata(metadata)

    # Make sure the required models are created
    create_db_process = environment.run_command(["createdb"], metadata.project_path)
    create_db_process.communicate()

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
                if response.ok:
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
        assert response.ok

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
            ["docker-compose", "down"], cwd=metadata.project_path, check=True
        )
        secho("Docker shut down successfully.")
