from typing import Any, List, Literal, Optional, Union

import pytest

from mountaineer.client_builder.types import (
    DictOf,
    ListOf,
    LiteralOf,
    Or,
    SetOf,
    TupleOf,
    TypeDefinition,
    TypeParser,
    get_union_types,
    is_union_type,
)


class TypeComparisonHelpers:
    @staticmethod
    def are_types_equivalent(type1: Any, type2: Any) -> bool:
        """
        Recursively compares two type definitions for logical equivalence,
        handling nested types and different ordering of union types.
        """
        if isinstance(type1, Or) and isinstance(type2, Or):
            return TypeComparisonHelpers.are_or_types_equivalent(type1, type2)

        if isinstance(type1, LiteralOf) and isinstance(type2, LiteralOf):
            return set(type1.values) == set(type2.values)

        if isinstance(type1, TypeDefinition) and isinstance(type2, TypeDefinition):
            return TypeComparisonHelpers.are_type_definitions_equivalent(type1, type2)

        return bool(type1 == type2)

    @staticmethod
    def find_matching_type(target: Any, candidates: tuple[Any, ...]) -> bool:
        """
        Finds a matching type in candidates that is equivalent to the target.
        Handles unhashable types by doing direct comparisons.
        """
        return any(
            TypeComparisonHelpers.are_types_equivalent(target, candidate)
            for candidate in candidates
        )

    @staticmethod
    def are_or_types_equivalent(type1: Or, type2: Or) -> bool:
        """
        Compares two Or types for equivalence, handling different ordering of types.
        Uses list-based comparison instead of sets for unhashable types.
        """
        if len(type1.types) != len(type2.types):
            return False

        # Convert to lists to maintain order and handle unhashable types
        types1 = list(type1.types)
        types2 = list(type2.types)

        # For each type in types1, find and remove a matching type in types2
        remaining_types2 = list(types2)
        for t1 in types1:
            found_match = False
            for i, t2 in enumerate(remaining_types2):
                if TypeComparisonHelpers.are_types_equivalent(t1, t2):
                    remaining_types2.pop(i)
                    found_match = True
                    break
            if not found_match:
                return False

        return len(remaining_types2) == 0

    @staticmethod
    def are_type_definitions_equivalent(
        def1: TypeDefinition, def2: TypeDefinition
    ) -> bool:
        """
        Compares two TypeDefinition instances for equivalence by comparing their attributes.
        """
        if type(def1) != type(def2):
            return False

        # Get all relevant attributes (those that define the type)
        attrs = [
            attr
            for attr in dir(def1)
            if not attr.startswith("_") and not callable(getattr(def1, attr))
        ]

        # Compare each attribute recursively
        return all(
            TypeComparisonHelpers.are_types_equivalent(
                getattr(def1, attr), getattr(def2, attr)
            )
            for attr in attrs
        )

    @staticmethod
    def describe_type_difference(type1: Any, type2: Any) -> str:
        """
        Returns a detailed description of why two types are different.
        Useful for debugging test failures.
        """
        if type(type1) != type(type2):
            return f"Type mismatch: {type(type1)} != {type(type2)}"

        if isinstance(type1, Or) and isinstance(type2, Or):
            if len(type1.types) != len(type2.types):
                return f"Or types have different lengths: {len(type1.types)} != {len(type2.types)}"
            return f"Or types contain different types: {type1.types} != {type2.types}"

        if isinstance(type1, LiteralOf) and isinstance(type2, LiteralOf):
            if set(type1.values) != set(type2.values):
                return f"LiteralOf values differ: {set(type1.values)} != {set(type2.values)}"

        if isinstance(type1, TypeDefinition) and isinstance(type2, TypeDefinition):
            attrs = [
                attr
                for attr in dir(type1)
                if not attr.startswith("_") and not callable(getattr(type1, attr))
            ]
            for attr in attrs:
                v1, v2 = getattr(type1, attr), getattr(type2, attr)
                if not TypeComparisonHelpers.are_types_equivalent(v1, v2):
                    return f"Attribute '{attr}' differs: {v1} != {v2}"

        return f"Values differ: {type1} != {type2}"


@pytest.fixture
def parser():
    return TypeParser()


@pytest.fixture
def type_compare():
    return TypeComparisonHelpers()


class TestUnionTypeDetection:
    @pytest.mark.parametrize(
        "type_input,expected",
        [
            (Union[str, int], True),
            (Optional[str], True),
            (str | int, True),
            (str | None, True),
            (list[int], False),
            (dict[str, int], False),
            (tuple[int, str], False),
            (set[float], False),
            (List[int], False),
            (int, False),
            (Any, False),
        ],
    )
    def test_is_union_type(self, type_input, expected):
        assert is_union_type(type_input) == expected

    @pytest.mark.parametrize(
        "type_input,expected",
        [
            (Union[str, int], [str, int]),
            (Optional[str], [str, type(None)]),
            (str | int, [str, int]),
            (str | None, [str, type(None)]),
            (int | str | float, [int, str, float]),
            (str | int | None, [str, int, type(None)]),
        ],
    )
    def test_get_union_types(self, type_input, expected):
        result = get_union_types(type_input)
        assert set(result) == set(expected)

    def test_get_union_types_invalid(self):
        with pytest.raises(ValueError):
            get_union_types(list[int])


class TestModernTypeSyntax:
    @pytest.mark.parametrize(
        "input_type,expected_type,expected_attributes",
        [
            (str | int, Or, {"types": (str, int)}),
            (str | None, Or, {"types": (str, type(None))}),
            (int | str | float, Or, {"types": (int, str, float)}),
            (list[int], ListOf, {"type": int}),
            (dict[str, int], DictOf, {"key_type": str, "value_type": int}),
            (tuple[str, int], TupleOf, {"types": (str, int)}),
            (set[int], SetOf, {"type": int}),
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
        self, parser, type_compare, input_type, expected_type, expected_attributes
    ):
        result = parser.parse_type(input_type)
        assert isinstance(result, expected_type)
        expected = expected_type(**expected_attributes)
        assert type_compare.are_types_equivalent(result, expected)

    def test_complex_modern_nested_types(self, parser, type_compare):
        complex_type = dict[str, list[tuple[int | None, str] | set[bool]]]
        result = parser.parse_type(complex_type)

        expected = DictOf(
            key_type=str,
            value_type=ListOf(
                type=Or(
                    types=(
                        TupleOf(types=(Or(types=(int, type(None))), str)),
                        SetOf(type=bool),
                    )
                )
            ),
        )

        assert type_compare.are_types_equivalent(result, expected)

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
        result = parser.parse_type(input_type)
        assert isinstance(result, TypeDefinition)


class TestLiteralTypes:
    @pytest.mark.parametrize(
        "input_type,expected_type,expected_attributes",
        [
            (Literal["a", "b"], LiteralOf, {"values": ["a", "b"]}),
            (Literal[1, 2, 3], LiteralOf, {"values": [1, 2, 3]}),
            (Literal[True, False], LiteralOf, {"values": [True, False]}),
            (Literal[None], LiteralOf, {"values": [None]}),
            (Literal["a", 1, True, None], LiteralOf, {"values": ["a", 1, True, None]}),
            (list[Literal["a", "b"]], ListOf, {"type": LiteralOf(values=["a", "b"])}),
            (
                dict[str, Literal[1, 2, 3]],
                DictOf,
                {"key_type": str, "value_type": LiteralOf(values=[1, 2, 3])},
            ),
            (
                Literal["a", "b"] | int,
                Or,
                {"types": (LiteralOf(values=["a", "b"]), int)},
            ),
            (
                dict[Literal["x", "y"], list[Literal[1, 2] | str]],
                DictOf,
                {
                    "key_type": LiteralOf(values=["x", "y"]),
                    "value_type": ListOf(
                        type=Or(types=(LiteralOf(values=[1, 2]), str))
                    ),
                },
            ),
        ],
    )
    def test_literal_types(
        self, parser, type_compare, input_type, expected_type, expected_attributes
    ):
        result = parser.parse_type(input_type)
        assert isinstance(result, expected_type)
        expected = expected_type(**expected_attributes)
        assert type_compare.are_types_equivalent(result, expected)

    def test_invalid_literal_values(self, parser):
        with pytest.raises(TypeError):
            parser.parse_type(Literal[object()])

        with pytest.raises(TypeError):
            parser.parse_type(Literal[[1, 2, 3]])

        with pytest.raises(TypeError):
            parser.parse_type(Literal[{"a": 1}])
