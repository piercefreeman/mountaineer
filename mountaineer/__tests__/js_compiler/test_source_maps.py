from pathlib import Path
from re import sub as re_sub

import pytest

from mountaineer import mountaineer as mountaineer_rs  # type: ignore
from mountaineer.__tests__.fixtures import get_fixture_path
from mountaineer.js_compiler.source_maps import (
    SourceMapParser,
    SourceMapSchema,
    get_cleaned_js_contents,
    make_source_map_paths_absolute,
    update_source_map_path,
)
from mountaineer.test_utilities import benchmark_function


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


@pytest.mark.asyncio
@benchmark_function(0.2)
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

    def make_map_metadata(
        line_number: int, column_number: int, source_line: int, source_column: int
    ) -> mountaineer_rs.MapMetadata:
        """
        Workaround to deal with rust's MapMetadata constructor
        only accepting line number and column number.

        """
        metadata = mountaineer_rs.MapMetadata(
            line_number=line_number,
            column_number=column_number,
        )
        metadata.source_index = 0
        metadata.source_line = source_line
        metadata.source_column = source_column
        metadata.symbol_index = 0
        return metadata

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
        (12882, 13): make_map_metadata(
            line_number=12882,
            column_number=13,
            source_line=500,
            source_column=10,
        ),
        (6333, 26): make_map_metadata(
            line_number=6333,
            column_number=13,
            source_line=600,
            source_column=20,
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
