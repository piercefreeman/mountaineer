import asyncio
import json
import os
import socket
import subprocess
import time
from contextlib import contextmanager
from pathlib import Path
from shutil import copytree
from threading import Thread

import httpx
import pytest
import uvicorn
from pydantic import BaseModel

from mountaineer.__tests__.fixtures import get_fixture_path
from mountaineer.actions.passthrough_dec import passthrough
from mountaineer.actions.sideeffect_dec import sideeffect
from mountaineer.app import AppController
from mountaineer.client_builder.builder import APIBuilder
from mountaineer.controller import ControllerBase
from mountaineer.render import Metadata, RenderBase


class IncrementCountRequest(BaseModel):
    count: int


class GetMessageResponse(BaseModel):
    message: str


class HomeRender(RenderBase):
    current_count: int
    render_token: int


class DetailRender(RenderBase):
    item_id: str


class HomeController(ControllerBase):
    url = "/"
    view_path = "/app/home/page.tsx"

    def __init__(self):
        super().__init__()
        self.current_count = 0
        self.render_count = 0

    def render(self) -> HomeRender:
        self.render_count += 1
        return HomeRender(
            current_count=self.current_count,
            render_token=self.render_count,
            metadata=Metadata(title="Home"),
        )

    @sideeffect
    def increment_count(self, payload: IncrementCountRequest) -> None:
        self.current_count += payload.count

    @sideeffect(reload=(HomeRender.current_count,))
    def increment_count_only(self, payload: IncrementCountRequest) -> None:
        self.current_count += payload.count

    @passthrough
    def get_message(self) -> GetMessageResponse:
        return GetMessageResponse(message=f"count={self.current_count}")


class DetailController(ControllerBase):
    url = "/detail/{item_id}/"
    view_path = "/app/detail/page.tsx"

    def render(self, item_id: str) -> DetailRender:
        return DetailRender(
            item_id=item_id,
            metadata=Metadata(title=f"Detail: {item_id}"),
        )


@pytest.mark.integration_tests
def test_generated_use_server_roundtrip(tmp_path: Path):
    view_root = tmp_path / "views"
    copytree(get_fixture_path("generated_client_project"), view_root)

    app = AppController(view_root=view_root)
    home_controller = HomeController()
    app.register(home_controller)
    app.register(DetailController())
    app.app.get("/_healthz")(lambda: {"ok": True})

    asyncio.run(APIBuilder(app).build_use_server())

    _run_command(
        ["npm", "install", "--no-fund", "--no-audit"],
        cwd=view_root,
        env=dict(os.environ, CI="1"),
    )

    initial_server_data = {
        home_controller.__class__.__name__: home_controller.render().model_dump(
            mode="json"
        )
    }

    with _run_uvicorn_server(app.app) as base_url:
        _run_command(
            [
                "npm",
                "run",
                "test",
                "--",
                "--runInBand",
                "__tests__/generated_client_roundtrip_test.ts",
            ],
            cwd=view_root,
            env=dict(
                os.environ,
                CI="1",
                MOUNTAINEER_BASE_URL=base_url,
                MOUNTAINEER_SERVER_DATA_JSON=json.dumps(initial_server_data),
            ),
        )


def _run_command(command: list[str], *, cwd: Path, env: dict[str, str]):
    result = subprocess.run(
        command,
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    if result.returncode != 0:
        raise AssertionError(
            f"Command failed: {' '.join(command)}\n"
            f"stdout:\n{result.stdout}\n"
            f"stderr:\n{result.stderr}"
        )


def _find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


@contextmanager
def _run_uvicorn_server(app):
    port = _find_free_port()

    class TestServer(uvicorn.Server):
        def install_signal_handlers(self) -> None:
            return None

    server = TestServer(
        uvicorn.Config(
            app,
            host="127.0.0.1",
            port=port,
            log_level="error",
            ws="none",
        )
    )

    thread = Thread(target=server.run, daemon=True)
    thread.start()

    base_url = f"http://127.0.0.1:{port}"
    deadline = time.time() + 10
    last_error: Exception | None = None

    while time.time() < deadline:
        try:
            response = httpx.get(f"{base_url}/_healthz", timeout=0.5)
            if response.status_code == 200:
                break
        except httpx.RequestError as exc:
            last_error = exc

        time.sleep(0.1)
    else:
        server.should_exit = True
        thread.join(timeout=5)
        raise AssertionError(f"Timed out waiting for uvicorn to start: {last_error}")

    try:
        yield base_url
    finally:
        server.should_exit = True
        thread.join(timeout=5)
        if thread.is_alive():
            raise AssertionError("Uvicorn test server did not shut down cleanly")
