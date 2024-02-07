from asyncio import create_task
from pathlib import Path
from uuid import uuid4

import pytest
from requests import get

from create_filzl_app.builder import (
    build_project,
    environment_from_metadata,
    should_copy_path,
)
from create_filzl_app.generation import ProjectMetadata


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
    # product(
    #    # Use poetry
    #    [False, True],
    #    # Use tailwind
    #    [False, True],
    # ),
    [
        (True, True),
    ],
)
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
    # TODO: Flag to only run on CI extended integration testing
    metadata = ProjectMetadata(
        project_name="my_project",
        author="John Appleseed",
        project_path=Path(tmpdir),
        use_poetry=use_poetry,
        use_tailwind=use_tailwind,
    )

    build_project(metadata)

    # Now launch the server in the background
    environment = environment_from_metadata(metadata)
    task = create_task(environment.run_command(["runserver"], metadata.project_path))

    # Perform the fetch tests

    response = get("http://localhost:5006")
    assert response.ok

    response = get(f"http://localhost:5006/detail/{uuid4()}")
    assert response.ok

    response = get("http://localhost:5006/not_found")
    assert not response.ok

    # Now we can kill the server
    task.cancel()
    await task
