from typing import Any, List, Optional, Union

import pytest

from mountaineer.client_builder.types import (
    DictOf,
    ListOf,
    Or,
    SetOf,
    TupleOf,
    TypeDefinition,
    TypeParser,
    get_union_types,
    is_union_type,
)


# Test cases for is_union_type function
@pytest.mark.parametrize(
    "type_input,expected",
    [
        (Union[str, int], True),
        (Optional[str], True),  # Optional is a Union with None
        (str | int, True),  # Modern union syntax
        (str | None, True),  # Modern optional syntax
        (list[int], False),
        (dict[str, int], False),
        (tuple[int, str], False),
        (set[float], False),
        (List[int], False),
        (int, False),
        (Any, False),
    ],
)
def test_is_union_type(type_input, expected):
    assert is_union_type(type_input) == expected


# Test cases for get_union_types function
@pytest.mark.parametrize(
    "type_input,expected",
    [
        (Union[str, int], [str, int]),
        (Optional[str], [str, type(None)]),
        (str | int, [str, int]),  # Modern union syntax
        (str | None, [str, type(None)]),  # Modern optional syntax
        (int | str | float, [int, str, float]),  # Multi-type union
        (str | int | None, [str, int, type(None)]),  # Complex optional
    ],
)
def test_get_union_types(type_input, expected):
    result = get_union_types(type_input)
    assert set(result) == set(expected)  # Order might vary between Python versions


def test_get_union_types_invalid():
    with pytest.raises(ValueError):
        get_union_types(list[int])


# Test cases for TypeParser with modern syntax
class TestTypeParserModernSyntax:
    @pytest.fixture
    def parser(self):
        return TypeParser()

    @pytest.mark.parametrize(
        "input_type,expected_type,expected_attributes",
        [
            # Modern union syntax
            (str | int, Or, {"types": (str, int)}),
            (str | None, Or, {"types": (str, type(None))}),
            (int | str | float, Or, {"types": (int, str, float)}),
            # Lowercase generic types
            (list[int], ListOf, {"type": int}),
            (dict[str, int], DictOf, {"key_type": str, "value_type": int}),
            (tuple[str, int], TupleOf, {"types": (str, int)}),
            (set[int], SetOf, {"type": int}),
            # Nested modern syntax
            (list[str | int], ListOf, {"type": Or(types=(str, int))}),
            (
                dict[str, list[int]],
                DictOf,
                {"key_type": str, "value_type": ListOf(type=int)},
            ),
            (
                tuple[int, str | None],
                TupleOf,
                {"types": (int, Or(types=(str, type(None))))},
            ),
            # Complex combinations
            (
                dict[str | int, list[tuple[int, str]]],
                DictOf,
                {
                    "key_type": Or(types=(str, int)),
                    "value_type": ListOf(type=TupleOf(types=(int, str))),
                },
            ),
            (
                list[dict[str, int | None]],
                ListOf,
                {"type": DictOf(key_type=str, value_type=Or(types=(int, type(None))))},
            ),
        ],
    )
    def test_modern_type_syntax(
        self, parser, input_type, expected_type, expected_attributes
    ):
        result = parser.parse_type(input_type)
        assert isinstance(result, expected_type)
        for attr, expected_value in expected_attributes.items():
            actual_value = getattr(result, attr)
            if isinstance(expected_value, tuple):
                # Instead of using sets, compare lengths and membership
                assert len(actual_value) == len(expected_value)
                for expected_item, actual_item in zip(
                    sorted(expected_value, key=str), sorted(actual_value, key=str)
                ):
                    if isinstance(expected_item, Or) and isinstance(actual_item, Or):
                        assert len(expected_item.types) == len(actual_item.types)
                        assert all(
                            t1 == t2
                            for t1, t2 in zip(
                                sorted(expected_item.types, key=str),
                                sorted(actual_item.types, key=str),
                            )
                        )
                    else:
                        assert expected_item == actual_item
            else:
                if isinstance(expected_value, Or) and isinstance(actual_value, Or):
                    assert len(expected_value.types) == len(actual_value.types)
                    assert all(
                        t1 == t2
                        for t1, t2 in zip(
                            sorted(expected_value.types, key=str),
                            sorted(actual_value.types, key=str),
                        )
                    )
                else:
                    assert actual_value == expected_value


# Integration tests for modern syntax
class TestTypeParserModernIntegration:
    @pytest.fixture
    def parser(self):
        return TypeParser()

    def test_complex_modern_nested_types(self, parser):
        # Modern syntax with multiple nesting levels
        complex_type = dict[str, list[tuple[int | None, str] | set[bool]]]
        result = parser.parse_type(complex_type)

        assert isinstance(result, DictOf)
        assert result.key_type == str
        assert isinstance(result.value_type, ListOf)
        assert isinstance(result.value_type.type, Or)

        # Check the union members
        union_types = result.value_type.type.types
        assert len(union_types) == 2

        # Convert to list and check types without assuming order
        union_types_list = list(union_types)
        found_tuple = False
        found_set = False

        for type_ in union_types_list:
            if isinstance(type_, TupleOf):
                found_tuple = True
                # Verify tuple structure
                assert len(type_.types) == 2
                assert isinstance(type_.types[0], Or)
                assert set(type_.types[0].types) == {int, type(None)}
                assert type_.types[1] == str
            elif isinstance(type_, SetOf):
                found_set = True
                assert type_.type == bool

        assert (
            found_tuple and found_set
        ), f"Both TupleOf and SetOf types should be present in the union, received: {union_types_list}"

    @pytest.mark.parametrize(
        "input_type",
        [
            dict[str | int, list[set[bool] | tuple[int, ...]]],
            list[dict[str | None, set[int | str]]],
            tuple[list[int | None], dict[str, set[bool | None]]],
            set[tuple[int | None, str | bool]],
        ],
    )
    def test_various_modern_combinations(self, parser, input_type):
        """Test that various complex modern type combinations can be parsed without errors"""
        result = parser.parse_type(input_type)
        assert isinstance(result, TypeDefinition)
