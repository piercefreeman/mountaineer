from pathlib import Path

import pytest

from filzl.client_interface.paths import (
    ManagedViewPath,
    generate_relative_import,
    is_path_file,
)
from filzl.controller import ControllerBase


@pytest.mark.parametrize(
    "path,expected_is_file",
    [
        (
            Path("fake-dir/fileA.js"),
            True,
        ),
        (
            Path("fake-dir/folder"),
            False,
        ),
        (
            Path("fake-dir/.hidden-folder"),
            False,
        ),
        (
            Path("fake-dir/.hidden-file.js"),
            True,
        ),
    ],
)
def test_is_path_file_heuristic(path: Path, expected_is_file: Path):
    """
    By providing paths that don't actually exist, we force our function
    to use the heuristic
    """
    assert not path.exists()
    assert is_path_file(path) == expected_is_file


@pytest.mark.parametrize(
    "current_import,desired_import,strip_js_extensions,expected",
    [
        (Path("src/fileA.js"), Path("src/fileB.js"), True, "./fileB"),
        (
            Path("src/fileA.js"),
            Path("src/subdir/fileB.js"),
            True,
            "./subdir/fileB",
        ),
        (Path("src/subdir/fileA.js"), Path("src/fileB.js"), True, "../fileB"),
        (
            Path("src/subdir/fileA.js"),
            Path("src/folderB/fileB.js"),
            True,
            "../folderB/fileB",
        ),
        (
            Path(
                "/Users/root/projects/filzl/my_website/my_website/views/app/home/_server"
            ),
            Path(
                "/Users/root/projects/filzl/my_website/my_website/views/_server/server.tsx"
            ),
            True,
            "../../../_server/server",
        ),
        (
            Path("src/subdir/fileA.js"),
            Path("src/folderB/fileB.js"),
            False,
            "../folderB/fileB.js",
        ),
    ],
)
def test_generate_relative_import(
    current_import: Path,
    desired_import: Path,
    strip_js_extensions: bool,
    expected: str,
):
    assert (
        generate_relative_import(
            current_import, desired_import, strip_js_extensions=strip_js_extensions
        )
        == expected
    )


def test_managed_view_path_constructors():
    # Test root view construction - unless created with the class constructor
    # we don't know that the path is in fact a root view
    assert ManagedViewPath("not_root_view").is_root_link is False
    assert ManagedViewPath.from_view_root("root_view").is_root_link is True

    # Test link creation maintains the root view status
    root_path = ManagedViewPath.from_view_root("root")
    assert isinstance(root_path / "file.psx", ManagedViewPath)
    assert isinstance(Path("other_path") / ManagedViewPath("file.psx"), ManagedViewPath)

    # Make sure that is_root_link is not inherited
    assert (root_path / "file.psx").is_root_link is False

def test_managed_view_paths_code_directories(tmpdir):
    root_path = ManagedViewPath.from_view_root(tmpdir)
    assert root_path.get_managed_code_dir() == root_path / "_server"
    assert root_path.get_managed_static_dir() == root_path / "_static"
    assert root_path.get_managed_ssr_dir() == root_path / "_ssr"

    # Non-root paths should only yield the server directory
    non_root_path = root_path / "subdir"
    non_root_path.mkdir()

    assert non_root_path.get_managed_code_dir() == root_path / "subdir" / "_server"
    with pytest.raises(ValueError):
        non_root_path.get_managed_static_dir()
    with pytest.raises(ValueError):
        non_root_path.get_managed_ssr_dir()

def test_managed_view_paths_get_controller(tmpdir):
    root_path = ManagedViewPath.from_view_root(tmpdir)

    class ExampleController(ControllerBase):
        view_path = "/detail/page.tsx"

        def render(self) -> None:
            pass

    assert root_path.get_controller_view_path(ExampleController()) == root_path / "detail/page.tsx"
