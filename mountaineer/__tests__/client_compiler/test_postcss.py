from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from mountaineer.client_compiler.postcss import PostCSSBundler
from mountaineer.paths import ManagedViewPath


@pytest.mark.parametrize(
    "view_path, expected_output_name",
    [
        (
            "root_style.css",
            "root_style.css",
        ),
        (
            "root_style.scss",
            "root_style.css",
        ),
        (
            "home/style.css",
            "home_style.css",
        ),
        (
            "home/nested/other/style.css",
            "home_nested_other_style.css",
        ),
    ],
)
def test_get_style_output_name(view_path: str, expected_output_name: str):
    view_root = ManagedViewPath.from_view_root("fake-root")

    bundler = PostCSSBundler()
    assert bundler.get_style_output_name(view_root / view_path) == expected_output_name


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "css_path_str",
    [
        "styles.css",  # Standard case
        "components/nested/styles.css",  # Nested case
        "styles.scss",  # File with different extension
    ],
)
async def test_process_css_uses_absolute_paths(css_path_str: str):
    # Setup test data and paths
    package_root = ManagedViewPath.from_view_root("/fake/root")
    view_root = ManagedViewPath.from_view_root("/fake/root/views")
    css_path = view_root / css_path_str

    # Setup bundler with metadata
    bundler = PostCSSBundler()
    bundler.metadata = MagicMock()
    bundler.metadata.package_root_link = package_root

    # Create cli_path for the mock
    cli_path = Path("/fake/root/views/node_modules/.bin/postcss")

    # Mock the process result
    mock_process = AsyncMock()
    mock_process.communicate.return_value = (b"", b"")
    mock_process.returncode = 0

    with (
        TemporaryDirectory() as temp_dir_name,
        patch.object(bundler, "postcss_is_installed", return_value=(True, cli_path)),
        patch("asyncio.create_subprocess_exec", return_value=mock_process) as mock_exec,
        patch("tempfile.TemporaryDirectory") as mock_temp_dir,
    ):
        temp_dir_path = Path(temp_dir_name)
        mock_temp_dir.return_value.__enter__.return_value = str(temp_dir_path)

        # Mock output file
        with patch.object(Path, "read_text", return_value="processed CSS"):
            # Call the method
            result = await bundler.process_css(css_path)

            # Verify the result
            assert result == "processed CSS"

            # Verify subprocess was called with absolute paths
            mock_exec.assert_called_once()
            args, kwargs = mock_exec.call_args

            # Check command has absolute paths
            assert str(cli_path.absolute()) == args[0]
            assert str(css_path.absolute()) == args[1]
            assert "-o" == args[2]

            # Check that env params are set
            assert kwargs.get("cwd") == css_path.get_root_link().absolute()

            env = kwargs.get("env", {})
            assert "NODE_PATH" in env
            assert str(package_root.absolute() / "node_modules") == env["NODE_PATH"]
