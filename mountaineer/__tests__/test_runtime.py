from pathlib import Path
from unittest.mock import patch

from mountaineer.app import AppController
from mountaineer.controller import ControllerBase
from mountaineer.graph.cache import ControllerProdCache
from mountaineer.render import RenderNull
from mountaineer.runtime import (
    ControllerAssets,
    FrontendDevServer,
    FrontendManifest,
    ImportTarget,
    RuntimePaths,
    RuntimePayload,
    ServerConfig,
    build_vite_client,
    build_vite_stylesheets,
    set_runtime_payload,
)


def test_runtime_payload_connects_production_assets(tmp_path: Path):
    view_root = tmp_path / "package" / "views"
    (view_root / "home").mkdir(parents=True)
    (view_root / "home" / "page.tsx").write_text("export default function Home() {}")

    coordinated_assets = tmp_path / "coordinated"
    coordinated_assets.mkdir()
    ssr_path = coordinated_assets / "runtime_controller.js"
    ssr_path.write_text("server bundle")

    payload = RuntimePayload(
        schema_version=1,
        mode="production",
        generation=4,
        import_=ImportTarget(package="package", webcontroller="package.app:controller"),
        server=ServerConfig(host="127.0.0.1", port=5006),
        paths=RuntimePaths(
            project_root=tmp_path,
            python_package_root=tmp_path / "package",
            frontend_root=view_root,
            view_root=view_root,
            static_root=view_root / "_static",
            ssr_root=view_root / "_ssr",
        ),
        frontend=FrontendManifest(
            controllers={
                "runtime_controller": ControllerAssets(
                    ssr_path=ssr_path,
                    ssr_map_path=None,
                    client_scripts=["runtime_controller.js?v=coordinated"],
                )
            },
            static_artifact_shas={"runtime_controller.js": "coordinated"},
        ),
    )
    set_runtime_payload(payload)
    try:
        app = AppController(view_root=tmp_path / "ignored")

        class RuntimeController(ControllerBase):
            url = "/"
            view_path = "home/page.tsx"

            def render(self) -> None:
                return None

        controller = RuntimeController()
        app.register(controller)
        cache = controller._definition.resolve_cache()  # type: ignore[union-attr]

        assert isinstance(cache, ControllerProdCache)
        assert cache.cached_server_script == "server bundle"
        assert controller._bundled_scripts == ["runtime_controller.js?v=coordinated"]
        assert app.get_build_metadata().static_artifact_shas == {
            "runtime_controller.js": "coordinated"
        }
        assert not app.development_enabled
    finally:
        set_runtime_payload(None)


def test_vite_client_builds_route_entrypoints(tmp_path: Path):
    view_root = tmp_path / "package" / "views"
    page = view_root / "app" / "home" / "page.tsx"
    page.parent.mkdir(parents=True)
    page.write_text("export default function Home() { return <div /> }")
    styles = view_root / "app" / "main.css"
    styles.write_text("body { color: hotpink; }")
    payload = RuntimePayload(
        schema_version=1,
        mode="development",
        generation=1,
        import_=ImportTarget(package="package", webcontroller="package.app:controller"),
        server=ServerConfig(host="127.0.0.1", port=5006),
        paths=RuntimePaths(
            project_root=tmp_path,
            python_package_root=tmp_path / "package",
            frontend_root=view_root,
            view_root=view_root,
            static_root=view_root / "_static",
            ssr_root=view_root / "_ssr",
        ),
        frontend=FrontendManifest(
            controllers={},
            static_artifact_shas={},
            dev_server=FrontendDevServer(origin="http://127.0.0.1:5173"),
        ),
    )
    set_runtime_payload(payload)
    try:
        imports = build_vite_client("home_controller", [str(page)])
        assert imports is not None
        app = AppController(view_root=view_root)
        with patch("mountaineer.app.render_ssr", return_value="<main>Home</main>"):
            response = app.compile_html(
                "server bundle",
                RenderNull(),
                {"HomeController": RenderNull()},
                inline_client_script=None,
                external_client_imports=imports,
            )
    finally:
        set_runtime_payload(None)

    assert imports == ["http://127.0.0.1:5173/.mountaineer-vite/home_controller.js"]
    assert build_vite_stylesheets(payload) == [
        (
            f"http://127.0.0.1:5173/@fs/{styles.resolve().as_posix()}?direct",
            styles.resolve().as_posix(),
        )
    ]
    html = response.body.decode()
    assert html.index('rel="stylesheet"') < html.index("</head>") < html.index("<body>")
    entry = view_root / ".mountaineer-vite" / "home_controller.tsx"
    bootstrap = view_root / ".mountaineer-vite" / "home_controller.js"
    assert f'from "/@fs/{page.as_posix()}"' in entry.read_text()
    assert f'import "/@fs/{styles.as_posix()}"' in entry.read_text()
    assert 'import "/@vite/client"' in bootstrap.read_text()
    assert 'import RefreshRuntime from "/@react-refresh"' in bootstrap.read_text()
