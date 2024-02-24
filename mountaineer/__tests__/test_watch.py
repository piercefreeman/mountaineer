from pathlib import Path

import pytest

from mountaineer.watch import ChangeEventHandler, PackageWatchdog


@pytest.mark.parametrize(
    "path, ignore_list, ignore_hidden, expected_ignore",
    [
        ("myproject/regular.py", ["__pycache__"], True, False),
        ("myproject/.hidden", [""], True, True),
        ("myproject/.hidden/subfile", [""], True, True),
        ("myproject/.hidden/subfile", [""], False, False),
        ("myproject/__cache__", ["__cache__"], True, True),
    ],
)
def test_ignore_path(
    path: str,
    ignore_list: list[str],
    ignore_hidden: bool,
    expected_ignore: bool,
):
    handler = ChangeEventHandler(
        [], ignore_list=ignore_list, ignore_hidden=ignore_hidden
    )
    assert handler.should_ignore_path(Path(path)) == expected_ignore


@pytest.mark.parametrize(
    "paths, expected_paths",
    [
        (
            # Unique paths
            ["myproject/regular.py", "myproject/.hidden"],
            ["myproject/regular.py", "myproject/.hidden"],
        ),
        (
            # Simple subdirectory
            ["myproject", "myproject/subdir"],
            ["myproject"],
        ),
        (
            # More specific directory first
            ["myproject/subdir1/subdir2", "myproject/subdir1"],
            ["myproject/subdir1"],
        ),
    ],
)
def test_merge_paths(paths: list[str], expected_paths: list[str]):
    handler = PackageWatchdog("mountaineer", [])
    assert set(handler.merge_paths(paths)) == {
        str(Path(path).absolute()) for path in expected_paths
    }
