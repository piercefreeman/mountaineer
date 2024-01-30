import pytest

from filzl.client_interface.typescript import TSLiteral


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
