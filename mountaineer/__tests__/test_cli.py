from pathlib import Path
from unittest.mock import ANY
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel

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
            '<div id="root">Passthrough: {"exception":"This is a test",'
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
