from __future__ import annotations

from dataclasses import dataclass
from hashlib import md5
from pathlib import Path
from typing import TYPE_CHECKING, cast
from urllib.parse import urlencode

from pydantic import BaseModel

from mountaineer import mountaineer as mountaineer_rs  # type: ignore
from mountaineer.logging import LOGGER
from mountaineer.paths import ManagedViewPath
from mountaineer.runtime import get_runtime_payload
from mountaineer.ssr import find_tsconfig
from mountaineer.static import get_static_path

if TYPE_CHECKING:
    from mountaineer.graph.app_graph import ControllerDefinition


@dataclass(frozen=True)
class FrontendEntry:
    server_script: str
    client_script: str | None = None
    client_imports: tuple[str, ...] = ()
    server_sourcemap: str | None = None


class BuildMetadata(BaseModel):
    static_artifact_shas: dict[str, str]


def write_build_metadata(view_root: ManagedViewPath) -> None:
    """
    Persist content hashes for the compiled static assets.

    :param view_root: The managed frontend directory containing the static assets
    """
    static_dir = view_root.get_managed_static_dir()
    metadata = BuildMetadata(
        static_artifact_shas={
            str(path.relative_to(static_dir)): md5(path.read_bytes()).hexdigest()
            for path in static_dir.rglob("*")
            if path.is_file()
        }
    )
    (view_root.get_managed_metadata_dir() / "metadata.json").write_text(
        metadata.model_dump_json()
    )


def resolve_frontend(
    definition: ControllerDefinition,
    *,
    node_modules_path: Path,
    live_reload_port: int,
    build_metadata: BuildMetadata | None,
) -> FrontendEntry:
    """
    Resolve and cache the frontend assets for a controller.

    :param definition: The controller and view paths to resolve
    :param node_modules_path: The installed frontend dependencies used for development compilation
    :param live_reload_port: The port injected into development bundles for live reload
    :param build_metadata: Content hashes for production assets, when available
    :return: The scripts and imports needed to render the controller
    :raises ValueError: If a required production artifact is missing
    """
    if definition.frontend is not None:
        return definition.frontend

    if definition.development_enabled:
        definition.frontend = _development_entry(
            definition, node_modules_path, live_reload_port
        )
    else:
        definition.frontend = _production_entry(definition, build_metadata)
    return definition.frontend


def _development_entry(
    definition: ControllerDefinition,
    node_modules_path: Path,
    live_reload_port: int,
) -> FrontendEntry:
    view_paths = definition.get_hierarchy_view_paths()
    tsconfig_path = find_tsconfig(view_paths)
    scripts, sourcemaps = mountaineer_rs.compile_independent_bundles(
        view_paths,
        str(node_modules_path.resolve()),
        "development",
        live_reload_port,
        str(get_static_path("live_reload.ts").resolve()),
        True,
        tsconfig_path,
    )

    payload = get_runtime_payload()
    if payload is not None and payload.dev_server_origin is not None:
        return FrontendEntry(
            server_script=cast(str, scripts[0]),
            server_sourcemap=cast(str | None, sourcemaps[0]),
            client_imports=(
                vite_client_url(
                    payload.dev_server_origin,
                    view_paths[0],
                    vite_style_paths(definition.view_root),
                ),
            ),
        )

    LOGGER.debug(
        "Compiling client-side bundle for %s",
        definition.controller.__class__.__name__,
    )
    client_scripts, _ = mountaineer_rs.compile_independent_bundles(
        view_paths,
        str(node_modules_path.resolve()),
        "development",
        live_reload_port,
        str(get_static_path("live_reload.ts").resolve()),
        False,
        tsconfig_path,
    )
    return FrontendEntry(
        server_script=cast(str, scripts[0]),
        server_sourcemap=cast(str | None, sourcemaps[0]),
        client_script=cast(str, client_scripts[0]),
    )


def _production_entry(
    definition: ControllerDefinition,
    build_metadata: BuildMetadata | None,
) -> FrontendEntry:
    script_name = definition.controller.script_name
    server_path = (
        definition.view_root.get_managed_ssr_dir(create_dir=False) / f"{script_name}.js"
    )
    client_name = f"{script_name}.js"
    client_path = (
        definition.view_root.get_managed_static_dir(create_dir=False) / client_name
    )
    for path in (server_path, client_path):
        if not path.is_file():
            raise ValueError(
                f"Missing frontend artifact {path}. Run the Mountaineer build command first."
            )

    client_hash = (
        build_metadata.static_artifact_shas.get(client_name)
        if build_metadata is not None
        else None
    )
    if client_hash is None:
        client_hash = md5(client_path.read_bytes()).hexdigest()

    source_map_path = server_path.with_suffix(".js.map")
    return FrontendEntry(
        server_script=server_path.read_text(),
        server_sourcemap=(
            source_map_path.read_text() if source_map_path.is_file() else None
        ),
        client_imports=(f"{definition.static_url}/{client_name}?v={client_hash}",),
    )


def vite_client_url(
    origin: str,
    view_paths: list[str],
    styles: list[Path],
) -> str:
    """
    Build the Vite URL that serves a controller's client entrypoint.

    :param origin: The Vite development server origin
    :param view_paths: The controller view hierarchy to bundle
    :param styles: The stylesheets to include in the bundle
    :return: The client entrypoint URL
    """
    query = urlencode(
        [
            *(("view", Path(path).resolve().as_posix()) for path in view_paths),
            *(("style", style.as_posix()) for style in styles),
        ]
    )
    return f"{origin}/@mountaineer/client?{query}"


def vite_stylesheets(frontend_root: Path) -> list[tuple[str, str]]:
    """
    Resolve development stylesheet URLs served by Vite.

    :param frontend_root: The root directory containing frontend sources
    :return: Pairs of Vite URLs and their source paths
    """
    payload = get_runtime_payload()
    if payload is None or payload.dev_server_origin is None:
        return []
    return [
        (
            f"{payload.dev_server_origin}/@fs/{style.as_posix()}?direct",
            style.as_posix(),
        )
        for style in vite_style_paths(frontend_root)
    ]


def vite_style_paths(frontend_root: Path) -> list[Path]:
    """
    Find source stylesheets while excluding generated and dependency directories.

    :param frontend_root: The root directory containing frontend sources
    :return: Absolute paths to the source stylesheets
    """
    ignored = {
        ".mountaineer",
        ".mountaineer-vite",
        "node_modules",
    }
    return [
        style.resolve()
        for style in sorted(frontend_root.rglob("*.css"))
        if not ignored.intersection(style.relative_to(frontend_root).parts)
    ]
