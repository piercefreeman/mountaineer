from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

PAYLOAD_PATH_ENV = "MOUNTAINEER_RUNTIME_PAYLOAD"


class ImportTarget(BaseModel):
    package: str
    webcontroller: str


class ServerConfig(BaseModel):
    host: str
    port: int


class RuntimePaths(BaseModel):
    project_root: Path
    python_package_root: Path
    frontend_root: Path
    view_root: Path
    static_root: Path
    ssr_root: Path


class ControllerAssets(BaseModel):
    ssr_path: Path
    ssr_map_path: Path | None
    client_scripts: list[str]


class FrontendDevServer(BaseModel):
    origin: str


class FrontendManifest(BaseModel):
    controllers: dict[str, ControllerAssets]
    static_artifact_shas: dict[str, str]
    dev_server: FrontendDevServer | None = None


class RuntimePayload(BaseModel):
    schema_version: Literal[1]
    mode: Literal["development", "production"]
    generation: int
    rebuild_generated: bool = True
    import_: ImportTarget = Field(alias="import")
    server: ServerConfig
    paths: RuntimePaths
    frontend: FrontendManifest

    model_config = {"populate_by_name": True}


_runtime_payload: RuntimePayload | None = None


def set_runtime_payload(payload: RuntimePayload | None) -> None:
    global _runtime_payload
    _runtime_payload = payload


def get_runtime_payload() -> RuntimePayload | None:
    if _runtime_payload is not None:
        return _runtime_payload
    payload_path = os.getenv(PAYLOAD_PATH_ENV)
    if payload_path is None:
        return None
    return RuntimePayload.model_validate_json(Path(payload_path).read_text())


def build_vite_client(
    script_name: str,
    view_paths: list[str],
) -> list[str] | None:
    payload = get_runtime_payload()
    if payload is None or payload.frontend.dev_server is None:
        return None

    entry_dir = payload.paths.frontend_root / ".mountaineer-vite"
    entry_dir.mkdir(parents=True, exist_ok=True)
    entry_path = entry_dir / f"{script_name}.tsx"
    bootstrap_path = entry_dir / f"{script_name}.js"

    imports = [
        f"import Layout{index} from {json.dumps(f'/@fs/{Path(path).as_posix()}')};"
        for index, path in enumerate(view_paths)
    ]
    for style in _vite_styles(payload):
        imports.append(f"import {json.dumps(f'/@fs/{style.as_posix()}')};")
    nested = "\n".join(
        [
            *[
                f"{'  ' * (index + 2)}<Layout{index}>"
                for index in range(len(view_paths))
            ],
            *[
                f"{'  ' * (index + 2)}</Layout{index}>"
                for index in reversed(range(len(view_paths)))
            ],
        ]
    )
    entry_source = "\n".join(
        [
            'import React from "react";',
            'import { hydrateRoot } from "react-dom/client";',
            *imports,
            "",
            "const Entrypoint = () => (",
            "  <>",
            nested,
            "  </>",
            ");",
            'const container = document.getElementById("root");',
            'if (!container) throw new Error("Mountaineer root element is missing");',
            "hydrateRoot(container, <Entrypoint />);",
            "",
        ]
    )
    bootstrap_source = "\n".join(
        [
            'import "/@vite/client";',
            'import RefreshRuntime from "/@react-refresh";',
            "RefreshRuntime.injectIntoGlobalHook(window);",
            "window.$RefreshReg$ = () => {};",
            "window.$RefreshSig$ = () => (type) => type;",
            "window.__vite_plugin_react_preamble_installed__ = true;",
            f"await import({json.dumps(f'./{script_name}.tsx')});",
            "",
        ]
    )
    _write_if_changed(entry_path, entry_source)
    _write_if_changed(bootstrap_path, bootstrap_source)
    return [
        f"{payload.frontend.dev_server.origin}/.mountaineer-vite/{bootstrap_path.name}"
    ]


def build_vite_stylesheets(payload: RuntimePayload) -> list[tuple[str, str]]:
    if payload.frontend.dev_server is None:
        return []
    return [
        (
            f"{payload.frontend.dev_server.origin}/@fs/{style.as_posix()}?direct",
            style.as_posix(),
        )
        for style in _vite_styles(payload)
    ]


def _vite_styles(payload: RuntimePayload) -> list[Path]:
    ignored_dirs = {
        ".mountaineer-vite",
        "node_modules",
        "_metadata",
        "_server",
        "_ssr",
        "_static",
    }
    return [
        style.resolve()
        for style in sorted(payload.paths.frontend_root.rglob("*.css"))
        if not ignored_dirs.intersection(
            style.relative_to(payload.paths.frontend_root).parts
        )
    ]


def _write_if_changed(path: Path, content: str) -> None:
    if not path.exists() or path.read_text() != content:
        path.write_text(content)


def serve_runtime(payload: RuntimePayload) -> None:
    """Coordinator child and production process entrypoint."""
    set_runtime_payload(payload)
    os.chdir(payload.paths.project_root)
    controller = asyncio.run(_prepare_controller(payload))

    import uvicorn

    uvicorn.run(
        controller.app,
        host=payload.server.host,
        port=payload.server.port,
        reload=False,
        access_log=False,
        log_level="warning",
    )


async def _prepare_controller(payload: RuntimePayload):
    # Keep user application imports inside each candidate worker.
    from mountaineer.development.isolation import IsolatedAppContext

    context = IsolatedAppContext.from_webcontroller(
        payload.import_.webcontroller,
        use_dev_exceptions=payload.mode == "development",
    )
    await context.initialize_app_state()
    if context.app_controller is None:
        raise RuntimeError("App controller did not initialize")

    if payload.mode == "development" and payload.rebuild_generated:
        if context.js_compiler is None or context.app_compiler is None:
            raise RuntimeError("Development compilers did not initialize")
        await context.js_compiler.build_use_server()
        await context.app_compiler.run_builder_plugins()

    return context.app_controller


def main() -> None:
    payload_path = os.environ[PAYLOAD_PATH_ENV]
    payload = RuntimePayload.model_validate_json(Path(payload_path).read_text())
    serve_runtime(payload)


if __name__ == "__main__":
    main()
