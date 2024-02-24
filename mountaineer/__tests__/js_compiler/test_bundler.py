from pathlib import Path
from re import sub as re_sub
from tempfile import TemporaryDirectory
from typing import Iterable
from unittest.mock import MagicMock, _Call, call, patch

import pytest

from mountaineer.js_compiler.base import ClientBundleMetadata
from mountaineer.js_compiler.bundler import JavascriptBundler
from mountaineer.paths import ManagedViewPath


class MockedESBuild:
    def __init__(self):
        self.calls: list[_Call] = []

    async def bundle(self, *args, outfile: Path, **kwargs):
        # Create something that looks like a real file
        outfile.parent.mkdir(parents=True, exist_ok=True)
        outfile.write_text("FAKE ESBUILD PACKAGE CONTENTS")
        (outfile.with_suffix(".js.map").write_text("FAKE ESBUILD PACKAGE SOURCE MAP"))
        self.calls.append(call(*args, outfile=outfile, **kwargs))


@pytest.fixture
def fake_view_root() -> Iterable[ManagedViewPath]:
    with TemporaryDirectory() as temp_dir_name:
        managed_view = ManagedViewPath.from_view_root(temp_dir_name)

        # Make fake expected directories
        (managed_view / "node_modules").mkdir()
        (managed_view / "package.json").write_text("{}")
        yield managed_view


@pytest.fixture
def mocked_esbuild():
    mocked_builder = MockedESBuild()

    with patch("mountaineer.js_compiler.bundler.ESBuildWrapper") as mock:
        mock.return_value = mocked_builder
        yield mocked_builder


@pytest.fixture(scope="function")
def base_javascript_bundler(mocked_esbuild: MagicMock) -> JavascriptBundler:
    from mountaineer.js_compiler.bundler import JavascriptBundler

    # Recycle this object every function call, since the end function will usually
    # modify the page_path or other instance variables
    return JavascriptBundler(
        root_element="root",
    )


def test_build_synthetic_endpoint(
    fake_view_root: ManagedViewPath, base_javascript_bundler: JavascriptBundler
):
    # The paths don't actually have to exist for this function
    page_path = fake_view_root / "detail" / "nested" / "page.tsx"

    (
        import_paths,
        content,
        endpoint_name,
    ) = base_javascript_bundler.build_synthetic_endpoint(
        page_path=page_path,
        layout_paths=[
            fake_view_root / "detail" / "layout.tsx",
            fake_view_root / "detail" / "nested" / "layout.tsx",
        ],
        # For ease of specifying the relative page paths, we make the test file
        # right in the root of the view directory
        output_path=fake_view_root / "dist" / "test_file.tsx",
    )

    # Should be ordered in the same hierarchy order as the layouts
    # so we can codify proper nesting behavior of layouts
    assert import_paths == [
        "import mountLiveReload from '../_server/live_reload';",
        "import Page from '../detail/nested/page';",
        "import Layout0 from '../detail/layout';",
        "import Layout1 from '../detail/nested/layout';",
    ]
    assert re_sub(r"\s+", "", content) == re_sub(
        r"\s+",
        "",
        (
            """
            const Entrypoint = () => {
                mountLiveReload({});
                return (
                    <Layout0>
                        <Layout1>
                            <Page />
                        </Layout1>
                    </Layout0>
                );
            };
            """
        ),
    )
    assert endpoint_name == "Entrypoint"


def test_build_synthetic_client_page(base_javascript_bundler: JavascriptBundler):
    # Test with simple string substitutions instead of real values so we can
    # be sure the resulting payload is dynamic.
    content = base_javascript_bundler.build_synthetic_client_page(
        synthetic_imports=[
            "SYNTHETIC_IMPORT_0",
            "SYNTHETIC_IMPORT_1",
        ],
        synthetic_endpoint="SYNTHETIC_ENDPOINT",
        synthetic_endpoint_name="SYNTHETIC_ENDPOINT_NAME",
    )

    assert re_sub(r"\s+", "", content) == re_sub(
        r"\s+",
        "",
        (
            """
            import * as React from 'react';
            import { hydrateRoot } from 'react-dom/client';
            SYNTHETIC_IMPORT_0
            SYNTHETIC_IMPORT_1

            SYNTHETIC_ENDPOINT

            const container = document.getElementById('root');
            hydrateRoot(container, <SYNTHETIC_ENDPOINT_NAME />);
            """
        ),
    )


def test_build_synthetic_ssr_page(base_javascript_bundler: JavascriptBundler):
    content = base_javascript_bundler.build_synthetic_ssr_page(
        synthetic_imports=[
            "SYNTHETIC_IMPORT_0",
            "SYNTHETIC_IMPORT_1",
        ],
        synthetic_endpoint="SYNTHETIC_ENDPOINT",
        synthetic_endpoint_name="SYNTHETIC_ENDPOINT_NAME",
    )

    assert re_sub(r"\s+", "", content) == re_sub(
        r"\s+",
        "",
        (
            """
            import * as React from 'react';
            import { renderToString } from 'react-dom/server';
            SYNTHETIC_IMPORT_0
            SYNTHETIC_IMPORT_1

            SYNTHETIC_ENDPOINT

            export const Index = () => renderToString(<SYNTHETIC_ENDPOINT_NAME />);
            """
        ),
    )


@pytest.mark.parametrize(
    "page_path, expected_layouts",
    [
        # These paths are assumed to be relative to our fake root view
        (
            Path("home/detail/page.tsx"),
            [
                Path("home/layout.tsx"),
                Path("home/detail/layout.tsx"),
            ],
        ),
        (
            Path("auth/page.tsx"),
            [Path("auth/layout.tsx")],
        ),
    ],
)
def test_sniff_for_layouts(
    page_path: Path,
    expected_layouts: list[Path],
    base_javascript_bundler: JavascriptBundler,
    fake_view_root: ManagedViewPath,
):
    # We don't have to actually add any values here, but we
    home_directory = fake_view_root / "home"
    home_detail_directory = home_directory / "detail"
    auth_directory = fake_view_root / "auth"

    home_directory.mkdir(parents=True)
    home_detail_directory.mkdir(parents=True)
    auth_directory.mkdir(parents=True)

    # Each of these directories should have a layout.tsx file in them
    (home_directory / "layout.tsx").touch()
    (home_detail_directory / "layout.tsx").touch()
    (auth_directory / "layout.tsx").touch()

    assert base_javascript_bundler.sniff_for_layouts(
        page_path=fake_view_root / page_path,
        view_root_path=fake_view_root,
    ) == [
        (fake_view_root / relative_path).resolve().absolute()
        for relative_path in expected_layouts
    ]


@pytest.mark.asyncio
async def test_convert(
    base_javascript_bundler: JavascriptBundler,
    fake_view_root: ManagedViewPath,
    mocked_esbuild: MockedESBuild,
):
    with (
        patch.object(base_javascript_bundler, "sniff_for_layouts") as sniff_for_layouts,
        patch.object(
            base_javascript_bundler, "build_synthetic_endpoint"
        ) as build_synthetic_endpoint,
        patch.object(
            base_javascript_bundler, "build_synthetic_client_page"
        ) as build_synthetic_client_page,
        patch.object(
            base_javascript_bundler, "build_synthetic_ssr_page"
        ) as build_synthetic_ssr_page,
    ):
        sniff_for_layouts.return_value = [
            fake_view_root / "layout.tsx",
            fake_view_root / "nested/layout.tsx",
        ]

        build_synthetic_endpoint.return_value = (
            ["import Page from './page';", "import Layout from './layout';"],
            "const Entrypoint = () => { return <Layout><Page /></Layout>; };",
            "Entrypoint",
        )

        build_synthetic_client_page.return_value = "CLIENT_PAGE"
        build_synthetic_ssr_page.return_value = "SSR_PAGE"

        output_bundle = await base_javascript_bundler.generate_js_bundle(
            current_path=fake_view_root / "page.tsx", metadata=ClientBundleMetadata()
        )

        # Assert that our build pipeline called our mocked esbuild_wrapper
        assert len(mocked_esbuild.calls) == 2
        assert mocked_esbuild.calls[0].kwargs["output_format"] == "esm"
        assert mocked_esbuild.calls[1].kwargs["output_format"] == "iife"
        assert mocked_esbuild.calls[1].kwargs["global_name"] == "SSR"

        # Assert the outputs
        expected_fake_str = "FAKE ESBUILD PACKAGE CONTENTS"
        expected_fake_map_str = "FAKE ESBUILD PACKAGE SOURCE MAP"

        assert output_bundle.client_compiled_contents == expected_fake_str
        assert output_bundle.client_source_map_contents == expected_fake_map_str
        assert output_bundle.server_compiled_contents == expected_fake_str
        assert output_bundle.server_source_map_contents == expected_fake_map_str


@pytest.mark.parametrize(
    "page_path, view_root_path, expected_throws",
    [
        # Valid page path and relative location
        (
            Path("home/detail/page.tsx"),
            Path("home"),
            False,
        ),
        # Similar path but different at the end
        (
            Path("home/detail/page.tsx"),
            Path("home/detail/nested"),
            True,
        ),
        # Totally separate path
        (
            Path("home/detail/page.tsx"),
            Path("other_path"),
            True,
        ),
        # Nested but not a page
        (
            Path("home/detail/nested/page.txt"),
            Path("home/detail/nested"),
            True,
        ),
    ],
)
def test_validate_nested_paths(
    page_path: Path,
    view_root_path: Path,
    expected_throws: bool,
    base_javascript_bundler: JavascriptBundler,
):
    if expected_throws:
        with pytest.raises(ValueError):
            base_javascript_bundler.validate_page(
                page_path=page_path, view_root_path=view_root_path
            )
    else:
        base_javascript_bundler.validate_page(
            page_path=page_path, view_root_path=view_root_path
        )
