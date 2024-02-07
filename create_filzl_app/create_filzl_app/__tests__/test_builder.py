import asyncio
from asyncio import create_task
from itertools import product
from pathlib import Path
from uuid import uuid4

import pytest
from click import secho
from requests import get

from create_filzl_app.builder import (
    build_project,
    environment_from_metadata,
    should_copy_path,
)
from create_filzl_app.generation import ProjectMetadata
from create_filzl_app.io import get_free_port
from create_filzl_app.templates import get_template_path


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
@pytest.mark.asyncio
async def test_valid_permutations(
    tmpdir: str,
    use_poetry: bool,
    use_tailwind: bool,
):
    """
    Ensures that regardless of the input parameters
    used to generate our new project, it will successfully
    run and return the expected endpoints.

    """
    # Assume the create-filzl-app project is in the same directory as the
    # main filzl package. We use a slight hack here assuming that our file
    # directory is oriented like "filzl/create_filzl_app/create_filzl_app/templates"
    # main package.
    main_filzl_path = get_template_path("../../../").resolve()

    # Verify this is pointing to where we expect
    if not (main_filzl_path / "pyproject.toml").exists():
        raise ValueError("Unable to find the main filzl package.")

    # TODO: Flag to only run on CI extended integration testing
    metadata = ProjectMetadata(
        project_name="my_project",
        author_name="John Appleseed",
        author_email="test@email.com",
        project_path=Path(tmpdir),
        use_poetry=use_poetry,
        use_tailwind=use_tailwind,
        filzl_dev_path=main_filzl_path,
    )

    build_project(metadata)

    app_test_port = get_free_port()
    secho(f"Found free port for test server: {app_test_port}", fg="green")

    # Now launch the server in the background
    environment = environment_from_metadata(metadata)
    task = create_task(
        environment.run_command(
            ["runserver", "--port", str(app_test_port)], metadata.project_path
        )
    )

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
        await asyncio.sleep(1)
        max_wait -= 1

    assert max_wait > 0, "Server start timed out."

    # Perform the fetch tests
    response = get(f"http://localhost:{app_test_port}")
    assert response.ok

    response = get(f"http://localhost:{app_test_port}/detail/{uuid4()}")
    assert response.ok

    response = get(f"http://localhost:{app_test_port}/not_found")
    assert not response.ok

    # Now we can kill the server
    task.cancel()
    try:
        await task
    except asyncio.exceptions.CancelledError:
        secho("Server shut down...")
