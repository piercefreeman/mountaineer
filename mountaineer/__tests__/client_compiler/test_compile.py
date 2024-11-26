from pathlib import Path

from mountaineer.app import AppController
from mountaineer.client_compiler.compile import ClientCompiler


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
