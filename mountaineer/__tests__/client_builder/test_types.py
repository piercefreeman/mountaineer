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

        non_type_1 = [
            child for child in def1.children if not isinstance(child, TypeDefinition)
        ]
        non_type_2 = [
            child for child in def2.children if not isinstance(child, TypeDefinition)
        ]

        if non_type_1 != non_type_2:
            return False

        child_types_1 = [
            child for child in def1.children if isinstance(child, TypeDefinition)
        ]
        child_types_2 = [
            child for child in def2.children if isinstance(child, TypeDefinition)
        ]

        if len(child_types_1) != len(child_types_2):
            return False

        for a, b in zip(child_types_1, child_types_2):
            if not TypeComparisonHelpers.are_types_equivalent(a, b):
                return False

        return True


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
        "input_type,expected_type",
        [
            (str | int, Or(str, int)),
            (str | None, Or(str, type(None))),
            (int | str | float, Or(int, str, float)),
            (list[int], ListOf(int)),
            (dict[str, int], DictOf(str, int)),
            (tuple[str, int], TupleOf(str, int)),
            (set[int], SetOf(int)),
            (list[str | int], ListOf(Or(str, int))),
            (
                dict[str, list[int]],
                DictOf(str, ListOf(int)),
            ),
            (
                tuple[int, str | None],
                TupleOf(int, Or(str, type(None))),
            ),
            (
                dict[str | int, list[tuple[int, str]]],
                DictOf(Or(str, int), ListOf(TupleOf(int, str))),
            ),
            (
                list[dict[str, int | None]],
                ListOf(DictOf(str, Or(int, type(None)))),
            ),
        ],
    )
    def test_modern_type_syntax(self, parser, type_compare, input_type, expected_type):
        result = parser.parse_type(input_type)
        assert isinstance(result, type(expected_type))
        assert type_compare.are_types_equivalent(result, expected_type)

    def test_complex_modern_nested_types(self, parser, type_compare):
        complex_type = dict[str, list[tuple[int | None, str] | set[bool]]]
        result = parser.parse_type(complex_type)

        expected = DictOf(
            key=str,
            value=ListOf(
                Or(
                    TupleOf(Or(int, type(None)), str),
                    SetOf(bool),
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
        "input_type,expected_type",
        [
            (Literal["a", "b"], LiteralOf("a", "b")),
            (Literal[1, 2, 3], LiteralOf(1, 2, 3)),
            (Literal[True, False], LiteralOf(True, False)),
            (Literal[None], LiteralOf(None)),
            (Literal["a", 1, True, None], LiteralOf("a", 1, True, None)),
            (list[Literal["a", "b"]], ListOf(LiteralOf("a", "b"))),
            (
                dict[str, Literal[1, 2, 3]],
                DictOf(str, LiteralOf(1, 2, 3)),
            ),
            (
                Literal["a", "b"] | int,
                Or(LiteralOf("a", "b"), int),
            ),
            (
                dict[Literal["x", "y"], list[Literal[1, 2] | str]],
                DictOf(LiteralOf("x", "y"), ListOf(type=Or(LiteralOf(1, 2), str))),
            ),
        ],
    )
    def test_literal_types(self, parser, type_compare, input_type, expected_type):
        result = parser.parse_type(input_type)
        assert isinstance(result, type(expected_type))
        assert type_compare.are_types_equivalent(result, expected_type)

    def test_invalid_literal_values(self, parser):
        with pytest.raises(TypeError):
            parser.parse_type(Literal[object()])

        with pytest.raises(TypeError):
            parser.parse_type(Literal[[1, 2, 3]])

        with pytest.raises(TypeError):
            parser.parse_type(Literal[{"a": 1}])
