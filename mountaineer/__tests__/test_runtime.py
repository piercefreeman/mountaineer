from pathlib import Path
from unittest.mock import patch

from mountaineer.app import AppController
from mountaineer.controller import ControllerBase
from mountaineer.frontend import (
    BuildMetadata,
    resolve_frontend,
    vite_stylesheets,
    write_build_metadata,
)
from mountaineer.paths import ManagedViewPath
from mountaineer.render import RenderNull
from mountaineer.runtime import RuntimePayload, ServerConfig, set_runtime_payload


class RuntimeController(ControllerBase):
    url = "/"
    view_path = "home/page.tsx"

    def render(self) -> None:
        return None


def runtime_payload(mode: str, *, dev_server_origin: str | None = None):
    return RuntimePayload(
        schema_version=1,
        mode=mode,
        generation=1,
        webcontroller="package.app:controller",
        server=ServerConfig(host="127.0.0.1", port=5006),
        dev_server_origin=dev_server_origin,
    )


def test_production_frontend_is_resolved_from_route_definition(tmp_path: Path):
    view_root = tmp_path / "views"
    page = view_root / "home" / "page.tsx"
    page.parent.mkdir(parents=True)
    page.write_text("export default function Home() {}")
    (view_root / ".mountaineer" / "ssr").mkdir(parents=True)
    (view_root / ".mountaineer" / "static").mkdir()
    (view_root / ".mountaineer" / "ssr" / "runtime_controller.js").write_text(
        "server bundle"
    )
    (view_root / ".mountaineer" / "static" / "runtime_controller.js").write_text(
        "client bundle"
    )

    set_runtime_payload(runtime_payload("production"))
    try:
        app = AppController(view_root=view_root)
        app.register(RuntimeController())
        definition = app.graph.get_definitions_for_cls(RuntimeController)[0]
        frontend = resolve_frontend(
            definition,
            node_modules_path=view_root / "node_modules",
            live_reload_port=0,
            build_metadata=BuildMetadata(
                static_artifact_shas={"runtime_controller.js": "coordinated"}
            ),
        )
    finally:
        set_runtime_payload(None)

    assert frontend.server_script == "server bundle"
    assert frontend.client_imports == ("/static/runtime_controller.js?v=coordinated",)
    assert not hasattr(definition.controller, "_ssr_path")
    assert not hasattr(definition.controller, "_bundled_scripts")


def test_vite_client_is_generated_without_route_files(tmp_path: Path):
    view_root = tmp_path / "views"
    page = view_root / "home" / "page.tsx"
    page.parent.mkdir(parents=True)
    page.write_text("export default function Home() { return <div /> }")
    styles = view_root / "main.css"
    styles.write_text("body { color: hotpink; }")

    payload = runtime_payload("development", dev_server_origin="http://127.0.0.1:5173")
    set_runtime_payload(payload)
    try:
        app = AppController(view_root=view_root)
        app.register(RuntimeController())
        definition = app.graph.get_definitions_for_cls(RuntimeController)[0]
        with patch(
            "mountaineer.frontend.mountaineer_rs.compile_independent_bundles",
            return_value=(["server bundle"], ["source map"]),
        ):
            frontend = resolve_frontend(
                definition,
                node_modules_path=view_root / "node_modules",
                live_reload_port=0,
                build_metadata=None,
            )
        with patch("mountaineer.app.render_ssr", return_value="<main>Home</main>"):
            response = app.compile_html(
                frontend.server_script,
                RenderNull(),
                {"RuntimeController": RenderNull()},
                inline_client_script=None,
                external_client_imports=list(frontend.client_imports),
            )
        stylesheets = vite_stylesheets(view_root)
    finally:
        set_runtime_payload(None)

    assert frontend.client_imports[0].startswith(
        "http://127.0.0.1:5173/@mountaineer/client?"
    )
    assert ".mountaineer-vite" not in frontend.client_imports[0]
    assert stylesheets == [
        (
            f"http://127.0.0.1:5173/@fs/{styles.resolve().as_posix()}?direct",
            styles.resolve().as_posix(),
        )
    ]
    html = response.body.decode()
    assert html.index('rel="stylesheet"') < html.index("</head>") < html.index("<body>")
    assert f"@fs/{styles.resolve().as_posix()}?direct" in html
    assert not (view_root / ".mountaineer-vite").exists()


def test_build_metadata_hashes_final_static_assets(tmp_path: Path):
    view_root = ManagedViewPath.from_view_root(tmp_path / "views")
    view_root.mkdir()
    static_dir = view_root.get_managed_static_dir()
    (static_dir / "app_main.css").write_text("body {}")
    (static_dir / "home.js").write_text("export default null")

    write_build_metadata(view_root)

    metadata = BuildMetadata.model_validate_json(
        (view_root.get_managed_metadata_dir() / "metadata.json").read_text()
    )
    assert set(metadata.static_artifact_shas) == {"app_main.css", "home.js"}
