import pytest

from mountaineer.client_compiler.build_metadata import BuildMetadata
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
    assert metadata.build_header(build_metadata=None) == expected_tags


@pytest.mark.parametrize(
    "metadata, build_metadata, expected_tags",
    [
        # Test static file with matching SHA
        (
            Metadata(
                links=[
                    LinkAttribute(
                        rel="stylesheet",
                        href="/static/css/style.css",
                        add_static_sha=True,
                    )
                ]
            ),
            BuildMetadata(static_artifact_shas={"css/style.css": "abc123"}),
            ['<link rel="stylesheet" href="/static/css/style.css?sha=abc123" />'],
        ),
        # Test multiple static files with matching SHAs
        (
            Metadata(
                links=[
                    LinkAttribute(
                        rel="stylesheet",
                        href="/static/css/style.css",
                        add_static_sha=True,
                    ),
                    LinkAttribute(
                        rel="stylesheet",
                        href="/static/css/other.css",
                        add_static_sha=True,
                    ),
                ]
            ),
            BuildMetadata(
                static_artifact_shas={
                    "css/style.css": "abc123",
                    "css/other.css": "def456",
                }
            ),
            [
                '<link rel="stylesheet" href="/static/css/style.css?sha=abc123" />',
                '<link rel="stylesheet" href="/static/css/other.css?sha=def456" />',
            ],
        ),
        # Test static file without matching SHA (should not modify URL)
        (
            Metadata(
                links=[
                    LinkAttribute(
                        rel="stylesheet",
                        href="/static/css/nonexistent.css",
                        add_static_sha=True,
                    )
                ]
            ),
            BuildMetadata(static_artifact_shas={"css/style.css": "abc123"}),
            ['<link rel="stylesheet" href="/static/css/nonexistent.css" />'],
        ),
        # Test mix of static and non-static files
        (
            Metadata(
                links=[
                    LinkAttribute(
                        rel="stylesheet",
                        href="/static/css/style.css",
                        add_static_sha=True,
                    ),
                    LinkAttribute(
                        rel="stylesheet", href="/css/external.css", add_static_sha=True
                    ),
                ]
            ),
            BuildMetadata(static_artifact_shas={"css/style.css": "abc123"}),
            [
                '<link rel="stylesheet" href="/static/css/style.css?sha=abc123" />',
                '<link rel="stylesheet" href="/css/external.css" />',
            ],
        ),
        # Test with add_static_sha=False
        (
            Metadata(
                links=[
                    LinkAttribute(
                        rel="stylesheet",
                        href="/static/css/style.css",
                        add_static_sha=False,
                    )
                ]
            ),
            BuildMetadata(static_artifact_shas={"css/style.css": "abc123"}),
            ['<link rel="stylesheet" href="/static/css/style.css" />'],
        ),
        # Test with no build_metadata
        (
            Metadata(
                links=[
                    LinkAttribute(
                        rel="stylesheet",
                        href="/static/css/style.css",
                        add_static_sha=True,
                    )
                ]
            ),
            None,
            ['<link rel="stylesheet" href="/static/css/style.css" />'],
        ),
        # Test with existing query parameters
        (
            Metadata(
                links=[
                    LinkAttribute(
                        rel="stylesheet",
                        href="/static/css/style.css?v=1.0",
                        add_static_sha=True,
                    )
                ]
            ),
            BuildMetadata(static_artifact_shas={"css/style.css": "abc123"}),
            ['<link rel="stylesheet" href="/static/css/style.css?v=1.0&sha=abc123" />'],
        ),
        # Test with mixed attributes and SHA
        (
            Metadata(
                links=[
                    LinkAttribute(
                        rel="stylesheet",
                        href="/static/css/style.css",
                        add_static_sha=True,
                        optional_attributes={
                            "media": "screen",
                            "crossorigin": "anonymous",
                        },
                    )
                ]
            ),
            BuildMetadata(static_artifact_shas={"css/style.css": "abc123"}),
            [
                '<link rel="stylesheet" href="/static/css/style.css?sha=abc123" media="screen" crossorigin="anonymous" />'
            ],
        ),
    ],
)
def test_build_header_with_sha(
    metadata: Metadata, build_metadata: BuildMetadata | None, expected_tags: list[str]
):
    """
    Test the SHA addition logic for static files in the build_header method.

    """
    assert metadata.build_header(build_metadata=build_metadata) == expected_tags


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


@pytest.mark.parametrize(
    "initial_url,new_sha,expected_url",
    [
        # No existing query parameters
        ("https://example.com/path", "abc123", "https://example.com/path?sha=abc123"),
        # Has existing sha parameter
        (
            "https://example.com/path?sha=old123",
            "new456",
            "https://example.com/path?sha=new456",
        ),
        # Has other query parameters but no sha
        (
            "https://example.com/path?param1=value1&param2=value2",
            "def789",
            "https://example.com/path?param1=value1&param2=value2&sha=def789",
        ),
        # Has multiple query parameters including sha
        (
            "https://example.com/path?param1=value1&sha=old123&param2=value2",
            "ghi012",
            "https://example.com/path?param1=value1&sha=ghi012&param2=value2",
        ),
        # URL with special characters
        (
            "https://example.com/path?param=special+value&sha=old",
            "jkl345",
            "https://example.com/path?param=special+value&sha=jkl345",
        ),
        # URL with fragment
        (
            "https://example.com/path?param=value#fragment",
            "mno678",
            "https://example.com/path?param=value&sha=mno678#fragment",
        ),
        # URL with empty query string
        ("https://example.com/path?", "pqr901", "https://example.com/path?sha=pqr901"),
        # URL with port number
        (
            "https://example.com:8080/path?param=value",
            "stu234",
            "https://example.com:8080/path?param=value&sha=stu234",
        ),
    ],
)
def test_link_attribute_set_sha(initial_url, new_sha, expected_url):
    link = LinkAttribute(rel="test", href=initial_url)
    link.set_sha(new_sha)
    assert link.href == expected_url
