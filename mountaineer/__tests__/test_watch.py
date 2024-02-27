from json import dumps as json_dumps
from pathlib import Path
from unittest.mock import patch

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


@pytest.mark.parametrize(
    "package_name, filename",
    [
        ("my-awesome-project", "my_awesome_project.pth"),
        ("MyAwesomeProject", "myawesomeproject.pth"),
    ],
)
def test_resolve_symbolic_links(package_name: str, filename: str, tmpdir: str):
    # pth files are in txt format and have an explicit link
    # to the real file
    tmp_root = Path(tmpdir)
    (tmp_root / filename).write_text("/path/to/realfile")

    watchdog = PackageWatchdog("mountaineer", [])
    with patch("importlib.metadata.Distribution") as mock_distribution:
        mock_distribution.name = package_name
        mock_distribution.files = [
            tmp_root / filename,
            tmp_root / "other_file",
        ]
        mock_distribution.locate_file.side_effect = lambda x: x

        assert watchdog.resolve_package_path(mock_distribution) == "/path/to/realfile"


@pytest.mark.parametrize(
    "package_name, egg_info_name",
    [
        (
            "my-awesome-project",
            "my_awesome_project-0.1.0.dist-info",
        ),
        (
            "MyAwesomeProject",
            "MyAwesomeProject-0.1.0.dist-info",
        ),
    ],
)
def test_resolve_dist_links(tmpdir: str, package_name: str, egg_info_name: str):
    # direct_url.json files are located within the application's egginfo
    # directory within a local venv
    tmp_root = Path(tmpdir)
    egg_info_path = tmp_root / egg_info_name
    egg_info_path.mkdir(exist_ok=True)

    (egg_info_path / "direct_url.json").write_text(
        json_dumps({"dir_info": {"editable": True}, "url": "file:///path/to/realfile"})
    )

    watchdog = PackageWatchdog("mountaineer", [])
    with patch("importlib.metadata.Distribution") as mock_distribution:
        mock_distribution.name = package_name
        mock_distribution.files = [
            egg_info_path / "direct_url.json",
            tmp_root / "other_file",
        ]
        mock_distribution.locate_file.side_effect = lambda x: x

        assert watchdog.resolve_package_path(mock_distribution) == "/path/to/realfile"
