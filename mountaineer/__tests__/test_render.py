import pytest

from mountaineer.render import (
    LinkAttribute,
    MetaAttribute,
    Metadata,
    ScriptAttribute,
    ThemeColorMeta,
    ViewportMeta,
)


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
    assert metadata.build_header() == expected_tags


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
    metadata = metadatas[0]
    for other_metadata in metadatas[1:]:
        metadata = metadata.merge(other_metadata)

    assert metadata == expected_metadata
