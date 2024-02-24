from pathlib import Path

import pytest

from mountaineer.controller import ControllerBase
from mountaineer.paths import (
    ManagedViewPath,
    generate_relative_import,
    is_path_file,
)


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
                "/Users/root/projects/mountaineer/my_website/my_website/views/app/home/_server"
            ),
            Path(
                "/Users/root/projects/mountaineer/my_website/my_website/views/_server/server.tsx"
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


def test_managed_view_path_not_inheriting_root_state():
    """
    Only ManagedViewPaths that are explicitly created with `from_view_root` should
    be considered root views. All other paths should be considered subviews.

    """
    root_path = ManagedViewPath.from_view_root("root_view")
    detail_path = root_path / "detail" / "page.tsx"
    not_root_path = ManagedViewPath("not_root_view")

    # Test root view construction - unless created with the class constructor
    # we don't know that the path is in fact a root view
    assert root_path.is_root_link is True
    assert detail_path.is_root_link is False
    assert not_root_path.is_root_link is False


def test_managed_view_path_inherits_root_pointer():
    """
    Ensure all path functions that create new paths will be of type
    ManagedViewPath instead of reverting to a Path.

    """
    root_path = ManagedViewPath.from_view_root("root_view")
    subpath = root_path / "subdir" / "file.tsx"

    def common_assert_path_type(path):
        assert isinstance(path, ManagedViewPath)
        assert path.is_root_link is False
        assert path.root_link == root_path

    # Test all path functions maintain the custom path class
    common_assert_path_type(subpath)
    common_assert_path_type(subpath.resolve())
    common_assert_path_type(subpath.absolute())
    common_assert_path_type(subpath.relative_to(root_path))
    common_assert_path_type(subpath.with_name("new_name.tsx"))
    common_assert_path_type(subpath.with_suffix(".js"))
    common_assert_path_type(subpath.parent)


def test_managed_view_paths_code_directories(tmpdir):
    """
    Ensure that the paths can correctly derive the managed folders.

    """
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
    """
    Ensure that we can get the full view's filesystem path from a controller.
    """
    root_path = ManagedViewPath.from_view_root(tmpdir)

    class ExampleController(ControllerBase):
        view_path = "/detail/page.tsx"

        def render(self) -> None:
            pass

    controller_path = root_path.get_controller_view_path(ExampleController())
    assert controller_path == root_path / "detail/page.tsx"
    assert controller_path.is_root_link is False
    assert controller_path.root_link == root_path


def test_copy():
    path = ManagedViewPath.from_view_root("root_view", package_root_link="package_root")
    new_path = path.copy()

    assert id(path) != id(new_path)
    assert str(path.root_link) == str(new_path.root_link)
    assert str(path.package_root_link) == str(new_path.package_root_link)
