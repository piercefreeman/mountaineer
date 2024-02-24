import pytest

from mountaineer.controller import ControllerBase
from mountaineer.render import (
    LinkAttribute,
    Metadata,
    RenderBase,
    ThemeColorMeta,
    ViewportMeta,
)


class StubRenderBase(RenderBase):
    pass


class StubController(ControllerBase):
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
    ],
)
def test_build_header(metadata: Metadata, expected_tags: list[str]):
    controller = StubController()
    assert controller.build_header(metadata) == expected_tags
