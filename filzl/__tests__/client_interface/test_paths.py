import pytest
from pathlib import Path
from filzl.client_interface.paths import generate_relative_import
from unittest.mock import patch


@pytest.mark.parametrize(
    "current_import,desired_import,current_is_file,desired_is_file,expected",
    [
        (Path("src/fileA.js"), Path("src/fileB.js"), True, True, "./fileB"),
        (
            Path("src/fileA.js"),
            Path("src/subdir/fileB.js"),
            True,
            True,
            "./subdir/fileB",
        ),
        (Path("src/subdir/fileA.js"), Path("src/fileB.js"), True, True, "../fileB"),
        (
            Path("src/subdir/fileA.js"),
            Path("src/folderB/fileB.js"),
            True,
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
            False,
            True,
            "../../../_server/server",
        ),
    ],
)
def test_generate_relative_import(
    current_import: Path,
    desired_import: Path,
    current_is_file: bool,
    desired_is_file: bool,
    expected: str,
):
    def is_file_mock_fn(*args, **kwargs):
        # Right now we only reference the is_file function to refer
        # to the current import path, not the destination
        return current_is_file

    # Mock the is_file function
    # Paths are slot-based so we need to mock the global instance
    # https://stackoverflow.com/questions/48864027/how-do-i-patch-the-pathlib-path-exists-method
    with patch.object(Path, "is_file") as is_file_mock:
        is_file_mock.side_effect = is_file_mock_fn
        assert generate_relative_import(current_import, desired_import) == expected
