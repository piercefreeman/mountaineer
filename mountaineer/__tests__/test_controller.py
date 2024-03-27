from pathlib import Path

import pytest

from mountaineer.controller import ControllerBase
from mountaineer.render import (
    LinkAttribute,
    MetaAttribute,
    Metadata,
    RenderBase,
    ScriptAttribute,
    ThemeColorMeta,
    ViewportMeta,
)


class StubRenderBase(RenderBase):
    pass


class StubController(ControllerBase):
    view_path = "/page.tsx"

    def render(self):
        return StubRenderBase()


@pytest.mark.parametrize(
    "metadata, expected_tags",
    [
        # Title
        (
            Metadata(
                title="MyTitle",
            ),
            ["<title>MyTitle</title>"],
        ),
        # Multiple links
        (
            Metadata(
                links=[
                    LinkAttribute(
                        rel="stylesheet",
                        href="/stylesheet1.css",
                    ),
                    LinkAttribute(
                        rel="stylesheet",
                        href="/stylesheet2.css",
                    ),
                ],
            ),
            [
                '<link rel="stylesheet" href="/stylesheet1.css" />',
                '<link rel="stylesheet" href="/stylesheet2.css" />',
            ],
        ),
        # Mixed meta tags
        (
            Metadata(
                metas=[
                    ThemeColorMeta(
                        color="#000000",
                    ),
                    ViewportMeta(
                        width="device-width",
                        initial_scale=1,
                        maximum_scale=2,
                        user_scalable=False,
                    ),
                ]
            ),
            [
                '<meta name="theme-color" content="#000000" />',
                '<meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=2.0, user-scalable=no" />',
            ],
        ),
        # Script tags
        (
            Metadata(
                scripts=[
                    ScriptAttribute(
                        src="/script1.js",
                    ),
                    ScriptAttribute(
                        src="/script2.js",
                        asynchronous=True,
                    ),
                    ScriptAttribute(
                        src="/script3.js",
                        defer=True,
                    ),
                    ScriptAttribute(
                        src="/script4.js",
                        optional_attributes={"test-attr": "test-value"},
                    ),
                ],
            ),
            [
                '<script src="/script1.js"></script>',
                '<script src="/script2.js" async></script>',
                '<script src="/script3.js" defer></script>',
                '<script src="/script4.js" test-attr="test-value"></script>',
            ],
        ),
    ],
)
def test_build_header(metadata: Metadata, expected_tags: list[str]):
    controller = StubController()
    assert controller._build_header(metadata) == expected_tags


COMPLEX_METADATA = Metadata(
    title="MyTitle",
    links=[
        LinkAttribute(
            rel="stylesheet",
            href="/stylesheet1.css",
        )
    ],
    metas=[
        MetaAttribute(
            name="theme-color",
            content="#000000",
        )
    ],
    scripts=[
        ScriptAttribute(
            src="/script1.js",
        )
    ],
)


@pytest.mark.parametrize(
    "metadatas, expected_metadata",
    [
        # A complex metadata definition should always echo its own definition
        ([COMPLEX_METADATA], COMPLEX_METADATA),
        # We shouldn't end up with duplicates
        (
            [
                COMPLEX_METADATA,
                COMPLEX_METADATA,
            ],
            COMPLEX_METADATA,
        ),
        # Test a simple merge of two different values on the same property
        (
            [
                Metadata(
                    links=[
                        LinkAttribute(
                            rel="stylesheet",
                            href="/stylesheet1.css",
                        )
                    ]
                ),
                Metadata(
                    links=[
                        LinkAttribute(
                            rel="stylesheet",
                            href="/stylesheet2.css",
                        )
                    ]
                ),
            ],
            Metadata(
                links=[
                    LinkAttribute(
                        rel="stylesheet",
                        href="/stylesheet1.css",
                    ),
                    LinkAttribute(
                        rel="stylesheet",
                        href="/stylesheet2.css",
                    ),
                ]
            ),
        ),
        # The first specified header should win.
        (
            [
                Metadata(title="Primary"),
                Metadata(title="Secondary"),
            ],
            Metadata(title="Primary"),
        ),
    ],
)
def test_merge_metadatas(metadatas: list[Metadata], expected_metadata: Metadata):
    controller = StubController()
    assert controller._merge_metadatas(metadatas) == expected_metadata


def test_resolve_paths(tmp_path: Path):
    view_base = tmp_path / "views"
    ssr_base = view_base / "_ssr"
    static_base = view_base / "_static"

    controller = StubController()
    assert not controller.resolve_paths(view_base)

    # Now create an actual view path that we can sniff
    # This will get further in the pipeline but still won't be valid
    # because we don't have any of the global script files
    view_base.mkdir()
    assert not controller.resolve_paths(view_base)

    # Now we create the SSR script file
    ssr_base.mkdir()
    (ssr_base / "stub_controller.js").touch()
    (ssr_base / "stub_controller.js.map").touch()
    assert not controller.resolve_paths(view_base)

    # Finally, create the static script file
    # Our hash has to be exactly 32 digits to match the regex
    static_base.mkdir()
    random_hash = "b5ecd0c4405374100d6ef93088b86898"
    (static_base / f"stub_controller-{random_hash}.js").touch()
    (static_base / f"stub_controller-{random_hash}.js.map").touch()
    assert controller.resolve_paths(view_base)

    # Now ensure that the paths are correctly set
    assert controller.view_base_path == view_base
    assert controller.ssr_path == ssr_base / "stub_controller.js"
    assert controller.bundled_scripts == [f"stub_controller-{random_hash}.js"]
