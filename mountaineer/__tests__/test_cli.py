import asyncio
import os
import re
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
from mountaineer import mountaineer as mountaineer_rs
from mountaineer.cli import find_packages_with_prefix
from mountaineer.development.isolation import IsolatedAppContext
from mountaineer.ssr import find_tsconfig
from mountaineer.static import get_static_path


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
    # symlinked version in the original package. We only have one dependency so we can
    # just replace the entire bundle.
    assert len(content["project"]["dependencies"]) == 1
    content["project"]["dependencies"] = [
        f"mountaineer @ file://{str(base_package_path)}"
    ]

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

    isolated_context = IsolatedAppContext.from_webcontroller(
        webcontroller="client_only_fixture.app:controller",
        use_dev_exceptions=False,
    )
    asyncio.run(isolated_context.initialize_app_state())

    assert isolated_context.app_controller is not None

    build_controllers = [
        controller_definition
        for controller_definition in isolated_context.app_controller.graph.controllers
        if controller_definition.controller._build_enabled
    ]
    all_view_paths = [
        view_path
        for controller_definition in build_controllers
        for view_path in controller_definition.get_hierarchy_view_paths()
    ]
    entrypoint_names = [
        controller_definition.controller.script_name
        for controller_definition in build_controllers
    ]

    client_bundle_result = mountaineer_rs.compile_production_bundle(
        all_view_paths,
        str(isolated_context.app_controller._view_root / "node_modules"),
        "production",
        False,
        str(get_static_path("live_reload.ts").resolve().absolute()),
        False,
        find_tsconfig(all_view_paths),
        entrypoint_names,
    )

    static_dir = package_dir / "views" / "_static"
    static_dir.mkdir(exist_ok=True)

    for entrypoint_name, content, map_content in zip(
        entrypoint_names,
        client_bundle_result["entrypoints"],
        client_bundle_result["entrypoint_maps"],
    ):
        (static_dir / f"{entrypoint_name}.js").write_text(content)
        (static_dir / f"{entrypoint_name}.map.js").write_text(map_content)

    for path, content in client_bundle_result["supporting"].items():
        (static_dir / path).write_text(content)

    _assert_relative_js_imports_resolve(static_dir)


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

    # Start the handle_runserver function in a process
    server_process = Popen(
        ["uv", "run", "runserver", "--port", str(port)],
        cwd=tmp_ci_webapp,
        env=uv_env,
    )
    test_file_path = tmp_ci_webapp / "ci_webapp" / "controllers" / "home.py"

    try:
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
        is_bound, status_code = await check_server_bound(port)
        assert is_bound, "Server is not bound to localhost:3000"
        assert status_code == 200, "Server is not returning 200 status code"
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

    _symlink_or_copy_dir(
        fixture_views_dir / "node_modules",
        views_dir / "node_modules",
    )

    (app_dir / "page.tsx").write_text(
        """
import React from "react";
import ClientOnlyWrapper from "./ClientOnlyWrapper";

const ClientOnlyPage = () => {
  return (
    <div>
      <h1>Client Only Test</h1>
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
import queueMicrotask from "queue-microtask";
import { browserOnlyValue } from "./browserOnlyDom";

queueMicrotask(() => undefined);

const BrowserOnlyClient = () => {
  return <div>{browserOnlyValue}</div>;
};

export default BrowserOnlyClient;
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


def _symlink_or_copy_dir(source: Path, target: Path) -> None:
    try:
        target.symlink_to(source, target_is_directory=True)
    except OSError:
        copytree(source, target)


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
