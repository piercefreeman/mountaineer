from pathlib import Path
from re import sub as re_sub

import pytest

from filzl.__tests__.fixtures import get_fixture_path
from filzl.client_builder.source_maps import (
    MapMetadata,
    SourceMapParser,
    SourceMapSchema,
    VLQDecoder,
    get_cleaned_js_contents,
    make_source_map_paths_absolute,
    update_source_map_path,
)
from filzl.test_utilities import benchmark_function


@pytest.mark.parametrize(
    "input_str, expected_output",
    [
        # Single-line comments
        ("var x = 5; // This is a comment", "var x = 5;"),
        # Multi-line comments
        (
            "var y = 10; /* Multi\nLine\nComment */ var z = 15;",
            "var y = 10;  var z = 15;",
        ),
        # Mixed comments
        ("// Comment\nvar a = 1; /* Comment */", "var a = 1;"),
        # No comments
        ("var b = 2;", "var b = 2;"),
        # Comments with URLs
        ("// Visit http://example.com", ""),
        # Comments in strings
        (
            "var url = 'http://example.com'; // comment",
            "var url = 'http://example.com';",
        ),
        # Nested comments (non-standard but for testing)
        ("/* Comment /* Nested Comment */ End */", "End */"),
        # Empty string
        ("", ""),
        # Whitespace handling
        ("   // Comment\nvar c = 3;   ", "var c = 3;"),
    ],
)
def test_get_cleaned_js_contents(input_str: str, expected_output: str):
    assert get_cleaned_js_contents(input_str) == expected_output


@pytest.mark.parametrize(
    "input_str, replace_path, expected_output",
    [
        # Standard replacement
        (
            "var testing; //# sourceMappingURL=myfile.js.map",
            "final_path.js.map",
            "var testing; //# sourceMappingURL=final_path.js.map",
        ),
        # Replacement of independent map paths
        (
            "var testing; //# sourceMappingURL=first.js.map //# sourceMappingURL=second.js.map",
            "final_path.js.map",
            "var testing; //# sourceMappingURL=final_path.js.map //# sourceMappingURL=final_path.js.map",
        ),
    ],
)
def test_update_source_map_path(
    input_str: str, replace_path: str, expected_output: str
):
    assert update_source_map_path(input_str, replace_path) == expected_output


def test_vlq_constants():
    """
    Validate our generated bit-masks and alphabet are as intended
    """
    decoder = VLQDecoder()
    assert len(decoder.alphabet) == 64
    assert format(decoder.sign_bit_mask, "000001")
    assert format(decoder.continuation_bit_mask, "100000")


@pytest.mark.parametrize(
    "encoded, expected_vit",
    [
        ("aAYQA", [13, 0, 12, 8, 0]),
        ("CAAA", [1, 0, 0, 0]),
        ("SAAAA", [9, 0, 0, 0, 0]),
        ("GAAA", [3, 0, 0, 0]),
        ("mCAAmC", [35, 0, 0, 35]),
        ("kBAChO", [18, 0, 1, -224]),
        ("AClrFA", [0, 1, -2738, 0]),
    ],
)
def test_parse_vlq(encoded: str, expected_vit: list[int]):
    decoder = VLQDecoder()
    assert decoder.parse_vlq(encoded) == expected_vit


@pytest.mark.asyncio
@benchmark_function(1.0)
async def test_parse_source_map_parse(
    start_timing,
    end_timing,
):
    parser = SourceMapParser(get_fixture_path("home_controller_source_map.js.map"))
    start_timing()
    parser.parse()
    end_timing()
    assert parser.source_map

    source_filenames = {
        Path(source_path).name for source_path in parser.source_map.sources
    }
    assert source_filenames == {
        "react.development.js",
        "index.js",
        "scheduler.development.js",
        "react-dom.development.js",
        "client.js",
        "synthetic_client.tsx",
        "live_reload.ts",
        "page.tsx",
        "useServer.ts",
        "api.ts",
        "links.ts",
        "actions.ts",
    }
    assert parser.get_original_location(37, 13)


def test_map_exception():
    exception_stacktrace = """
    Example client error
        at Page (<anonymous>:12882:13)
        at renderWithHooks (<anonymous>:6333:26)

    """

    parser = SourceMapParser("")
    parser.source_map = SourceMapSchema(
        version=3,
        sources=["test.ts"],
        names=["symbol_test1", "symbol_test2"],
        mappings="",
        sourceRoot="",
        file="test.js",
    )
    parser.parsed_mappings = {
        (12882, 13): MapMetadata(
            line_number=12882,
            column_number=13,
            source_index=0,
            source_line=500,
            source_column=10,
            symbol_index=0,
        ),
        (6333, 26): MapMetadata(
            line_number=6333,
            column_number=13,
            source_index=0,
            source_line=600,
            source_column=20,
            symbol_index=1,
        ),
    }

    assert re_sub(r"\s+", "", parser.map_exception(exception_stacktrace)) == re_sub(
        r"\s+",
        "",
        """
    Example client error
        at Page (test.ts:500:10)
        at renderWithHooks (test.ts:600:20)
    """,
    )


@pytest.mark.parametrize(
    "metadata_state, current_metadata, expected_metadata, expected_metadata_state",
    [
        (
            # Simple merge of relative values, same line
            MapMetadata(
                line_number=1,
                column_number=10,
                source_index=10,
                source_line=10,
                source_column=10,
                symbol_index=10,
            ),
            MapMetadata(
                line_number=1,
                column_number=20,
                source_index=20,
                source_line=20,
                source_column=20,
                symbol_index=20,
            ),
            MapMetadata(
                line_number=1,
                column_number=30,
                source_index=30,
                source_line=30,
                source_column=30,
                symbol_index=30,
            ),
            MapMetadata(
                line_number=1,
                column_number=30,
                source_index=30,
                source_line=30,
                source_column=30,
                symbol_index=30,
            ),
        ),
        (
            # Merge of values on a different line, should reset
            # the column number but leave everything else relative
            MapMetadata(
                line_number=1,
                column_number=10,
                source_index=10,
                source_line=10,
                source_column=10,
                symbol_index=10,
            ),
            MapMetadata(
                line_number=2,
                column_number=20,
                source_index=20,
                source_line=20,
                source_column=20,
                symbol_index=20,
            ),
            MapMetadata(
                line_number=2,
                column_number=20,
                source_index=30,
                source_line=30,
                source_column=30,
                symbol_index=30,
            ),
            MapMetadata(
                line_number=2,
                column_number=20,
                source_index=30,
                source_line=30,
                source_column=30,
                symbol_index=30,
            ),
        ),
    ],
)
def test_merge_metadatas(
    metadata_state: MapMetadata,
    current_metadata: MapMetadata,
    expected_metadata: MapMetadata,
    expected_metadata_state: MapMetadata,
):
    source_map = SourceMapParser("")
    assert (
        source_map.merge_relative_metadatas(
            metadata_state=metadata_state, current_metadata=current_metadata
        )
        == expected_metadata
    )
    assert metadata_state == expected_metadata_state


def test_make_source_map_paths_absolute():
    schema = SourceMapSchema(
        version=3,
        sources=["../../node_modules/sub_folder/test.ts"],
        names=["symbol_test1", "symbol_test2"],
        mappings="",
        sourceRoot="",
        file="test.js",
    )

    parsed_result = make_source_map_paths_absolute(
        schema.model_dump_json(),
        Path("/fakehome/user/project/app/fake/fake/test.js"),
    )

    assert SourceMapSchema.model_validate_json(parsed_result).sources == [
        "/fakehome/user/project/app/node_modules/sub_folder/test.ts"
    ]
