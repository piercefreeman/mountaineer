import asyncio
import os
import re
import signal
from html import unescape
from os import environ
from pathlib import Path
from random import uniform
from shutil import copytree, ignore_patterns
from subprocess import Popen
from time import sleep, time

import httpx
import pytest
import toml

from mountaineer.__tests__.fixtures import get_fixture_path
from mountaineer.cli import handle_build
from mountaineer.development.packages import find_packages_with_prefix
from mountaineer.io import get_free_port
from mountaineer.ssr import render_ssr


@pytest.fixture
def tmp_ci_webapp(tmp_path: Path):
    # Copy the full ci_webapp package so we can make local modifications
    # just within this test
    raw_package = get_fixture_path("ci_webapp")
    mutable_package = tmp_path / "ci_webapp"
    copytree(
        raw_package,
        mutable_package,
        ignore=ignore_patterns("node_modules", ".venv", ".mypy_cache", "__pycache__"),
    )

    pyproject_path = mutable_package / "pyproject.toml"
    base_package_path = (get_fixture_path("") / "../../../").resolve()

    with open(pyproject_path, "r") as file:
        content = toml.load(file)

    # Point uv to the absolute path of the local Mountaineer package.
    content["tool"]["uv"]["sources"]["mountaineer"]["path"] = str(base_package_path)

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


def test_handle_build_preserves_dynamic_import_graph_for_client_only_modules(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    package_dir = _create_client_only_fixture(tmp_path)
    monkeypatch.syspath_prepend(str(tmp_path))

    event_loop = asyncio.new_event_loop()
    asyncio.set_event_loop(event_loop)
    try:
        handle_build(
            webcontroller="client_only_fixture.app:controller",
            minify=True,
        )
    finally:
        if not event_loop.is_closed():
            event_loop.close()
        asyncio.set_event_loop(None)

    static_dir = package_dir / "views" / ".mountaineer" / "static"
    ssr_dir = package_dir / "views" / ".mountaineer" / "ssr"

    _assert_relative_js_imports_resolve(static_dir)
    html = render_ssr(
        (ssr_dir / "client_only_controller.js").read_text(),
        {},
        sourcemap=(ssr_dir / "client_only_controller.js.map").read_text(),
    )
    assert "<h1>Client Only Test</h1>" in html
    assert "Loading browser-only component" not in html


async def check_server_ready(port: int, timeout: int = 20):
    # The development proxy returns 503 while frontend tooling and the backend start.
    start_time = time()
    url = f"http://localhost:{port}"
    status_code = -1
    async with httpx.AsyncClient() as client:
        while time() - start_time < timeout:
            try:
                response = await client.get(url)
                status_code = response.status_code
                if status_code == 200:
                    return True, status_code
            except httpx.RequestError:
                pass
            await asyncio.sleep(0.1)
    return False, status_code


async def check_development_frontend(port: int):
    public_host = f"dev.mountaineer.test:{port}"
    async with httpx.AsyncClient(base_url=f"http://127.0.0.1:{port}") as client:
        response = await client.get("/", headers={"Host": public_host})
        assert response.status_code == 200

        asset_paths = [
            unescape(path)
            for _, path in re.findall(r"(?:src|href)=(['\"])(.*?)\1", response.text)
            if path.startswith("/__mountaineer__/")
        ]
        assert asset_paths

        client_path = next(
            path for path in asset_paths if "/@mountaineer/client?" in path
        )
        client_response = await client.get(client_path, headers={"Host": public_host})
        assert client_response.status_code == 200

        module_paths = set(
            re.findall(r'"(/__mountaineer__/[^\"]+)"', client_response.text)
        )
        assert module_paths
        for path in module_paths:
            module_response = await client.get(path, headers={"Host": public_host})
            assert module_response.status_code == 200, path

    reader, writer = await asyncio.open_connection("127.0.0.1", port)
    try:
        writer.write(
            (
                "GET /__mountaineer__/ HTTP/1.1\r\n"
                f"Host: {public_host}\r\n"
                "Upgrade: websocket\r\n"
                "Connection: Upgrade\r\n"
                "Sec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==\r\n"
                "Sec-WebSocket-Version: 13\r\n"
                "Sec-WebSocket-Protocol: vite-hmr\r\n"
                "\r\n"
            ).encode()
        )
        await writer.drain()
        response_headers = await asyncio.wait_for(
            reader.readuntil(b"\r\n\r\n"), timeout=5
        )
        assert response_headers.startswith(b"HTTP/1.1 101 Switching Protocols\r\n")
    finally:
        writer.close()
        await writer.wait_closed()


@pytest.mark.integration_tests
@pytest.mark.asyncio
async def test_runserver_with_user_modifications(tmp_ci_webapp: Path):
    port = get_free_port()

    uv_env = {
        key: value
        for key, value in environ.items()
        if not key.startswith("VIRTUAL_ENV")
    }

    # Sync the packages at the new path before starting the fixture app.
    return_code = Popen(["uv", "sync"], cwd=tmp_ci_webapp, env=uv_env).wait()
    assert return_code == 0

    return_code = Popen(
        ["npm", "install"], cwd=tmp_ci_webapp / "ci_webapp" / "views", env=uv_env
    ).wait()
    assert return_code == 0

    # The project's runserver command delegates to the native development server.
    server_process = Popen(
        ["uv", "run", "runserver", "--host", "0.0.0.0", "--port", str(port)],
        cwd=tmp_ci_webapp,
        env=uv_env,
    )
    test_file_path = tmp_ci_webapp / "ci_webapp" / "controllers" / "home.py"

    try:
        is_ready, status_code = await check_server_ready(port)
        assert is_ready, f"Server did not become ready (last status: {status_code})"
        await check_development_frontend(port)

        for _ in range(5):
            with open(test_file_path, "a") as f:
                print(f"Adding content to {test_file_path}")  # noqa: T201
                f.write("\npass\n")

            sleep(uniform(0.2, 2.0))

        # After all these random server restarts make sure that the
        # server is still running
        print(  # noqa: T201
            "Done with changes, checking that server will resolve if not immediately ready..."
        )
        is_ready, status_code = await check_server_ready(port)
        assert is_ready, f"Server did not recover (last status: {status_code})"
        print("Server is bound to expected port")  # noqa: T201
    finally:
        # Terminate the processes after test
        os.kill(server_process.pid, signal.SIGKILL)
        server_process.wait()


def _create_client_only_fixture(tmp_path: Path) -> Path:
    package_name = "client_only_fixture"
    package_dir = tmp_path / package_name
    views_dir = package_dir / "views"
    app_dir = views_dir / "app" / "client_only"

    app_dir.mkdir(parents=True)
    (package_dir / "__init__.py").write_text("")

    (package_dir / "app.py").write_text(
        """
from pathlib import Path

from mountaineer import AppController, ControllerBase, Metadata, RenderBase


class ClientOnlyRender(RenderBase):
    pass


class ClientOnlyController(ControllerBase):
    url = "/client-only"
    view_path = "/app/client_only/page.tsx"

    def render(self) -> ClientOnlyRender:
        return ClientOnlyRender(metadata=Metadata(title="Client Only"))


controller = AppController(view_root=Path(__file__).parent / "views")
controller.register(ClientOnlyController())
""".strip()
        + "\n"
    )

    fixture_views_dir = (
        get_fixture_path("ci_webapp") / "ci_webapp" / "views"
    ).resolve()
    (views_dir / "package.json").write_text(
        (fixture_views_dir / "package.json").read_text()
    )
    (views_dir / "tsconfig.json").write_text(
        (fixture_views_dir / "tsconfig.json").read_text()
    )

    (app_dir / "page.tsx").write_text(
        """
import React from "react";
import ClientOnlyWrapper from "./ClientOnlyWrapper";
import { sharedClientValue } from "./sharedClientValue";

const ClientOnlyPage = () => {
  return (
    <div>
      <h1>Client Only Test</h1>
      <span>{sharedClientValue}</span>
      <ClientOnlyWrapper />
    </div>
  );
};

export default ClientOnlyPage;
""".strip()
        + "\n"
    )

    (app_dir / "ClientOnlyWrapper.tsx").write_text(
        """
"use client";

import React, { type ComponentType, useEffect, useState } from "react";

const ClientOnlyWrapper = () => {
  const [ClientOnlyComponent, setClientOnlyComponent] =
    useState<ComponentType | null>(null);

  useEffect(() => {
    import("./BrowserOnlyClient").then((module) => {
      setClientOnlyComponent(() => module.default);
    });
  }, []);

  if (!ClientOnlyComponent) {
    return <div>Loading browser-only component...</div>;
  }

  return <ClientOnlyComponent />;
};

export default ClientOnlyWrapper;
""".strip()
        + "\n"
    )

    (app_dir / "BrowserOnlyClient.tsx").write_text(
        """
import React from "react";
import { browserOnlyValue } from "./browserOnlyDom";
import { sharedClientValue } from "./sharedClientValue";

queueMicrotask(() => undefined);

const BrowserOnlyClient = () => {
  return <div>{browserOnlyValue}:{sharedClientValue}</div>;
};

export default BrowserOnlyClient;
""".strip()
        + "\n"
    )

    (app_dir / "sharedClientValue.ts").write_text(
        """
export const sharedClientValue = "shared-client-value";
""".strip()
        + "\n"
    )

    (app_dir / "browserOnlyDom.ts").write_text(
        """
document.createElement("i");

export const browserOnlyValue = "browser-only-client";
""".strip()
        + "\n"
    )

    return package_dir


def _assert_relative_js_imports_resolve(static_dir: Path) -> None:
    import_patterns = (
        re.compile(r'from\s+["\'](\./[^"\']+\.js)["\']'),
        re.compile(r'import\s*\(\s*["\'](\./[^"\']+\.js)["\']\s*\)'),
        re.compile(r'import\s*["\'](\./[^"\']+\.js)["\']'),
    )

    missing_references: list[str] = []

    for bundle_path in sorted(static_dir.glob("*.js")):
        if bundle_path.name.endswith(".map.js"):
            continue

        contents = bundle_path.read_text()
        relative_imports = {
            match for pattern in import_patterns for match in pattern.findall(contents)
        }

        for relative_import in sorted(relative_imports):
            target_path = bundle_path.parent / relative_import
            if not target_path.exists():
                missing_references.append(f"{bundle_path.name} -> {relative_import}")

    assert not missing_references, (
        "Unresolved relative JavaScript imports in built static output:\\n"
        + "\\n".join(missing_references)
    )
