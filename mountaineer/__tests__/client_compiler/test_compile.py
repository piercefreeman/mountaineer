from pathlib import Path

from mountaineer.app import AppController
from mountaineer.client_compiler.compile import ClientCompiler
from mountaineer.controller import ControllerBase
from mountaineer.plugin import MountaineerPlugin


def test_build_static_metadata(tmpdir: Path):
    app = AppController(view_root=tmpdir)
    compiler = ClientCompiler(app=app)

    # Write test files to the view path to determine if we're able
    # to parse the whole file tree
    static_dir = compiler.view_root.get_managed_static_dir()

    (static_dir / "test_css.css").write_text("CSS_TEXT")

    (static_dir / "nested").mkdir(exist_ok=True)
    (static_dir / "nested" / "test_nested.css").write_text("CSS_TEXT")

    # File contents are the same - shas should be the same as well
    metadata = compiler._build_static_metadata()
    assert "test_css.css" in metadata.static_artifact_shas
    assert "nested/test_nested.css" in metadata.static_artifact_shas
    assert (
        metadata.static_artifact_shas["test_css.css"]
        == metadata.static_artifact_shas["nested/test_nested.css"]
    )


def test_get_static_files_ignores_managed_artifact_dirs(tmp_path: Path):
    app = AppController(view_root=tmp_path)
    compiler = ClientCompiler(app=app)

    (tmp_path / "app.tsx").write_text("export const app = true;")
    (tmp_path / "_server").mkdir()
    (tmp_path / "_server" / "generated.ts").write_text("export const generated = true;")
    (tmp_path / "_metadata").mkdir()
    (tmp_path / "_metadata" / "metadata.json").write_text("{}")

    static_files = list(compiler._get_static_files())

    assert static_files == [tmp_path / "app.tsx"]


def test_clear_managed_artifacts_preserves_plugin_assets(tmp_path: Path):
    host_view_root = tmp_path / "host_views"
    host_view_root.mkdir()
    (host_view_root / "_static").mkdir()
    (host_view_root / "_static" / "stale_host.js").write_text("stale")

    plugin_view_root = tmp_path / "plugin_views"
    plugin_view_root.mkdir()
    (plugin_view_root / "_static").mkdir()
    (plugin_view_root / "_ssr").mkdir()
    plugin_static = plugin_view_root / "_static" / "plugin_controller.js"
    plugin_ssr = plugin_view_root / "_ssr" / "plugin_controller.js"
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

    ClientCompiler(app=app).clear_managed_artifacts()

    assert not (host_view_root / "_static").exists()
    assert plugin_static.exists()
    assert plugin_ssr.exists()
