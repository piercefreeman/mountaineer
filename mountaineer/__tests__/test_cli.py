from pathlib import Path
from unittest.mock import ANY
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel

from mountaineer.cli import (
    IsolatedEnvProcess,
    IsolatedWatchConfig,
    find_packages_with_prefix,
)
from mountaineer.controllers.exception_controller import ExceptionController


def test_dev_exception_on_get(tmpdir: str):
    """
    Exceptions encountered during GET requests will affect the user's ability to render
    the page, so we should nicely format these on to the development server in-lieu of showing
    an empty page. Backend errors on the other hand are often used for validation and caught
    by the frontend, so we should not intercept these.

    """
    app = FastAPI()

    class EchoModel(BaseModel):
        value: str

    @app.get("/")
    def get():
        raise ValueError("This is a test")

    @app.post("/api", response_model=EchoModel)
    def post(content: EchoModel):
        return content

    fake_ssr_template = Path(tmpdir) / f"{uuid4()}.html"
    fake_ssr_template.write_text(
        """
        const SSR = {
            x: () => `Passthrough: ${JSON.stringify(SERVER_DATA)}`
        }
        """
    )

    exception_controller = ExceptionController()
    exception_controller.ssr_path = fake_ssr_template

    # Install our exception handler hook. The rest of the env process is unused, we just
    # need it for the mounted controller.
    # This is a hack to avoid calling run(), which will trigger an actual build
    env_process = IsolatedEnvProcess(IsolatedWatchConfig(webcontroller=""))
    env_process.exception_controller = exception_controller
    app.exception_handler(Exception)(env_process.handle_dev_exception)

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


def test_find_packages_with_prefix():
    # Choose some packages that we know will be in the test environment
    assert set(find_packages_with_prefix("fasta")) == {"fastapi"}
    assert set(find_packages_with_prefix("pydan")) == {
        "pydantic",
        "pydantic_core",
        "pydantic-settings",
    }
