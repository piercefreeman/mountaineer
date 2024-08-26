import asyncio
import os
import signal
from os import environ
from pathlib import Path
from random import uniform
from shutil import copytree
from subprocess import Popen
from time import sleep, time

import httpx
import pytest
import toml

from mountaineer.__tests__.fixtures import get_fixture_path
from mountaineer.cli import (
    find_packages_with_prefix,
)


@pytest.fixture
def tmp_ci_webapp(tmp_path: Path):
    # Copy the full ci_webapp package so we can make local modifications
    # just within this test
    raw_package = get_fixture_path("ci_webapp")
    mutable_package = tmp_path / "ci_webapp"
    copytree(raw_package, mutable_package)

    pyproject_path = mutable_package / "pyproject.toml"
    base_package_path = (get_fixture_path("") / "../../../").resolve()

    with open(pyproject_path, "r") as file:
        content = toml.load(file)

    # Point to the absolute path of the local mountaineer core package, versus the
    # symlinked version in the original package
    content["tool"]["poetry"]["dependencies"]["mountaineer"]["path"] = str(
        base_package_path
    )

    with open(pyproject_path, "w") as file:
        toml.dump(content, file)

    return mutable_package


def test_find_packages_with_prefix():
    # Choose some packages that we know will be in the test environment
    assert set(find_packages_with_prefix("fasta")) == {"fastapi"}
    assert set(find_packages_with_prefix("pydan")) == {
        "pydantic",
        "pydantic_core",
        "pydantic-settings",
    }


async def check_server_bound(port: int, timeout=8):
    # 5s hard timeout + 3s overhead
    # When the server restarting gets stuck it gets stuck permanently
    start_time = time()
    url = f"http://localhost:{port}"
    async with httpx.AsyncClient() as client:
        while time() - start_time < timeout:
            try:
                response = await client.get(url)
                return True, response.status_code
            except httpx.RequestError:
                pass
            await asyncio.sleep(0.1)
    return False, -1


@pytest.mark.integration_tests
@pytest.mark.asyncio
async def test_handle_runserver_with_user_modifications(tmp_ci_webapp: Path):
    # Ensure that there is no existing webapp running
    port = 5006
    url = f"http://localhost:{port}"
    async with httpx.AsyncClient() as client:
        try:
            await client.get(url, timeout=1)
            assert False, "The server is already running"
        except httpx.RequestError:
            pass

    poetry_env = {
        key: value
        for key, value in environ.items()
        if not key.startswith("VIRTUAL_ENV")
    }

    return_code = Popen(
        ["poetry", "lock", "--no-update"], cwd=tmp_ci_webapp, env=poetry_env
    ).wait()
    assert return_code == 0

    # We need to poetry install the packages at the new path
    return_code = Popen(["poetry", "install"], cwd=tmp_ci_webapp, env=poetry_env).wait()
    assert return_code == 0

    return_code = Popen(
        ["npm", "install"], cwd=tmp_ci_webapp / "ci_webapp" / "views", env=poetry_env
    ).wait()
    assert return_code == 0

    # Start the handle_runserver function in a process
    server_process = Popen(
        ["poetry", "run", "runserver", "--port", str(port)],
        cwd=tmp_ci_webapp,
        env=poetry_env,
    )
    test_file_path = tmp_ci_webapp / "ci_webapp" / "controllers" / "home.py"

    try:
        for _ in range(50):
            with open(test_file_path, "a") as f:
                print(f"Adding content to {test_file_path}")  # noqa: T201
                f.write("\npass\n")

            sleep(uniform(0.2, 2.0))

        # After all these random server restarts make sure that the
        # server is still running
        print(  # noqa: T201
            "Done with changes, checking that server will resolve if not immediately ready..."
        )
        is_bound, status_code = await check_server_bound(port)
        assert is_bound, "Server is not bound to localhost:3000"
        assert status_code == 200, "Server is not returning 200 status code"
        print("Server is bound to expected port")  # noqa: T201
    finally:
        # Terminate the processes after test
        os.kill(server_process.pid, signal.SIGINT)
        server_process.wait()
