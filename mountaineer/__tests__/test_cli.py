import asyncio
import os
import signal
from os import environ
from pathlib import Path
from random import uniform
from shutil import copytree
from subprocess import Popen
from time import sleep, time
from unittest.mock import ANY
from uuid import uuid4

import httpx
import pytest
import toml
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel

from mountaineer.__tests__.fixtures import get_fixture_path
from mountaineer.app import AppController
from mountaineer.cli import (
    IsolatedBuildConfig,
    IsolatedEnvProcess,
    find_packages_with_prefix,
)
from mountaineer.controller import ControllerBase
from mountaineer.controllers.exception_controller import ExceptionController


@pytest.fixture
def env_process(tmpdir: str):
    """
    Custom isolated environment process with a valid exception controller
    that works without a build.

    """
    fake_ssr_template_path = Path(tmpdir) / f"{uuid4()}.html"
    fake_ssr_template_path.write_text(
        """
        const SSR = {
            x: () => `Passthrough: ${JSON.stringify(SERVER_DATA)}`
        }
        """
    )

    # We don't want to test our default exception logic, which requires a full build
    # to derive the ssr page
    exception_controller = ExceptionController()
    exception_controller.ssr_path = fake_ssr_template_path

    # Install our exception handler hook. The rest of the env process is unused, we just
    # need it for the mounted controller.
    # This is a hack to avoid calling run(), which will trigger an actual build
    env_process = IsolatedEnvProcess(IsolatedBuildConfig(webcontroller=""))
    env_process.exception_controller = exception_controller

    return env_process


@pytest.fixture
def invalid_build_app_controller(env_process: IsolatedEnvProcess, tmp_path: Path):
    (tmp_path / "page.tsx").write_text(
        """
        import React from "react";
        export default function Page() {
            return <div id="root">Value</div>;
        }
        """
    )
    (tmp_path / "package.json").write_text("{}")
    (tmp_path / "node_modules").mkdir()

    class ValidControllerInvalidBuild(ControllerBase):
        url = "/"
        view_path = "/page.tsx"

        def render(self) -> None:
            pass

    app_controller = AppController(view_root=tmp_path)
    app_controller.register(ValidControllerInvalidBuild())
    app_controller.app.exception_handler(Exception)(env_process.handle_dev_exception)

    return app_controller


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


def test_dev_thrown_exception_on_get(env_process: IsolatedEnvProcess):
    """
    Exceptions encountered during GET requests will affect the user's ability to render
    the page, so we should nicely format these on to the development server in-lieu of showing
    an empty page. Backend errors on the other hand are often used for validation and caught
    by the frontend, so we should not intercept these.

    """
    app = FastAPI()
    app.exception_handler(Exception)(env_process.handle_dev_exception)

    class EchoModel(BaseModel):
        value: str

    @app.get("/")
    def get():
        raise ValueError("This is a test")

    @app.post("/api", response_model=EchoModel)
    def post(content: EchoModel):
        return content

    with TestClient(app=app, raise_server_exceptions=False) as test_client:
        response = test_client.get("/")
        assert response.status_code == 500
        assert (
            '<div id="root">Passthrough: {"ExceptionController":{"exception":"This is a test",'
            in response.text
        )

        response = test_client.post("/api", json={"value": 123})
        assert response.status_code == 422
        assert response.json() == {
            "detail": [
                {
                    "input": 123,
                    "loc": ["body", "value"],
                    "msg": ANY,
                    "type": "string_type",
                    "url": ANY,
                }
            ]
        }


def test_build_does_not_raise(
    invalid_build_app_controller: AppController,
    env_process: IsolatedEnvProcess,
):
    """
    Build errors in the isolated process shouldn't actually raise. If they do they
    will short-circuit the rest of our isolated watcher process (ie. won't actually
    bring up the `runserver`, which is not what we want).

    """
    env_process.run_build(invalid_build_app_controller)

    # Ensure that we've set the expected instance variable
    assert invalid_build_app_controller.build_exception is not None


def test_build_exception_on_get(
    invalid_build_app_controller: AppController,
    env_process: IsolatedEnvProcess,
):
    """
    Display build-time exceptions on the development server as well.

    """
    env_process.run_build(invalid_build_app_controller)

    # Also ensure that this exception is displayed on the development server
    with TestClient(
        app=invalid_build_app_controller.app, raise_server_exceptions=False
    ) as test_client:
        response = test_client.get("/")
        assert response.status_code == 500
        assert (
            # Thrown because we did not install any node modules in this test package
            'Could not resolve "react"' in response.text
        )


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
