import pytest

from filzl.client_builder.source_maps import (
    get_cleaned_js_contents,
    update_source_map_path,
)


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
