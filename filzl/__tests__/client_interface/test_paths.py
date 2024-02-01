from pathlib import Path

import pytest

from filzl.client_interface.paths import generate_relative_import, is_path_file


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
