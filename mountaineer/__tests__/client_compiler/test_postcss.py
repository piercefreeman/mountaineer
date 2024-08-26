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
