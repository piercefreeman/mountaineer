import asyncio
from pathlib import Path

from mountaineer.app import AppController
from mountaineer.client_builder.builder import APIBuilder
from mountaineer.controller import ControllerBase
from mountaineer.plugin import MountaineerPlugin
from mountaineer.render import RenderBase


def test_build_creates_mountaineer_indexes(tmp_path: Path):
    view_root = tmp_path / "views"
    page = view_root / "app" / "home" / "page.tsx"
    page.parent.mkdir(parents=True)
    page.write_text("export default function Home() { return null; }")

    class HomeRender(RenderBase):
        message: str

    class HomeController(ControllerBase):
        url = "/"
        view_path = "/app/home/page.tsx"

        def render(self) -> HomeRender:
            return HomeRender(message="hello")

    app = AppController(view_root=view_root)
    app.register(HomeController())
    asyncio.run(APIBuilder(app).build_use_server())

    root_index = (view_root / ".mountaineer" / "index.ts").read_text()
    local_index = (page.parent / ".mountaineer" / "index.ts").read_text()
    assert "export * from './api';" in root_index
    assert "export * from './controllers';" in root_index
    assert "export * from './links';" in root_index
    assert "export * from './models';" in local_index
    assert "export * from './useServer';" in local_index


def test_build_all_cleanup_preserves_plugin_assets(tmp_path: Path):
    host_view_root = tmp_path / "host_views"
    host_view_root.mkdir()
    (host_view_root / ".mountaineer" / "static").mkdir(parents=True)
    (host_view_root / ".mountaineer" / "static" / "stale_host.js").write_text("stale")

    plugin_view_root = tmp_path / "plugin_views"
    plugin_view_root.mkdir()
    (plugin_view_root / ".mountaineer" / "static").mkdir(parents=True)
    (plugin_view_root / ".mountaineer" / "ssr").mkdir()
    plugin_static = (
        plugin_view_root / ".mountaineer" / "static" / "plugin_controller.js"
    )
    plugin_ssr = plugin_view_root / ".mountaineer" / "ssr" / "plugin_controller.js"
    plugin_static.write_text("console.log('plugin');")
    plugin_ssr.write_text("export default null;")

    class HostController(ControllerBase):
        url = "/"
        view_path = "/host/page.tsx"

        def render(self) -> None:
            return None

    class PluginController(ControllerBase):
        url = "/plugin"
        view_path = "/plugin/page.tsx"

        def render(self) -> None:
            return None

    app = AppController(view_root=host_view_root)
    app.register(HostController())
    app.register(
        MountaineerPlugin(
            name="plugin-test",
            controllers=[PluginController],
            view_root=plugin_view_root,
        )
    )

    for view_root in APIBuilder(app)._get_all_root_views(build_enabled_only=True):
        view_root.clear_managed_artifact_dirs()

    assert not (host_view_root / ".mountaineer").exists()
    assert plugin_static.exists()
    assert plugin_ssr.exists()
