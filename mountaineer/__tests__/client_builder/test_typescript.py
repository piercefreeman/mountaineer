from re import sub as re_sub
from typing import Any

import pytest

from mountaineer.client_builder.typescript import (
    TSLiteral,
    python_payload_to_typescript,
)


@pytest.mark.parametrize(
    "input_a,input_b,expected_literal",
    [
        (TSLiteral("a"), TSLiteral("b"), TSLiteral("ab")),
        (TSLiteral("a"), "b", TSLiteral("ab")),
        ("a", TSLiteral("b"), TSLiteral("ab")),
    ],
)
def test_tsliteral_combine(input_a: str, input_b: str, expected_literal: TSLiteral):
    result = input_a + input_b

    # We first do an explicit check of TSLiteral, making sure that we're not just
    # getting a regular string back
    assert isinstance(result, TSLiteral)
    assert result == expected_literal


@pytest.mark.parametrize(
    "payload, expected_str",
    [
        (1, "1"),
        (1.0, "1.0"),
        ("a", "'a'"),
        (True, "true"),
        (False, "false"),
        (None, "null"),
        (TSLiteral("a"), "a"),
        ({"a": "b"}, "{'a': 'b'}"),
        (["a", "b"], "['a', 'b']"),
    ],
)
def test_python_payload_to_typescript_primitives(payload: Any, expected_str: str):
    assert re_sub(r"\s+", "", python_payload_to_typescript(payload)) == re_sub(
        r"\s+", "", expected_str
    )


@pytest.mark.parametrize(
    "payload, expected_str",
    [
        (
            {"a": {"b": "b", "c": 1, "d": TSLiteral("someVariable")}},
            (
                "{\n"
                "  'a': {\n"
                "    'b': 'b',\n"
                "    'c': 1,\n"
                "    'd': someVariable\n"
                "  }\n"
                "}"
            ),
        )
    ],
)
def test_python_payload_to_typescript_nested(payload: Any, expected_str: str):
    assert python_payload_to_typescript(payload) == expected_str


@pytest.mark.parametrize(
    "original_payload, expected_str",
    [
        # Should format as a consolidated literal
        (
            {"a": TSLiteral("a")},
            "{a}",
        ),
        # Not literal, should format as a string
        (
            {"a": "a"},
            "{'a': 'a'}",
        ),
        # Literal but different value, should map from a string to a variable
        (
            {"a": TSLiteral("b")},
            "{'a': b}",
        ),
    ],
)
def test_collapse_repeated_literals(
    original_payload: dict[str, str | TSLiteral], expected_str: str
):
    """
    If the key of our dictionary is a literal, and it's the same value as the key,
    we should collapse it into a single value.

    """
    assert re_sub(r"\s+", "", python_payload_to_typescript(original_payload)) == re_sub(
        r"\s+", "", expected_str
    )
