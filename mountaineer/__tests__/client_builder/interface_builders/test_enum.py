from enum import Enum, auto
from typing import Dict, List, Tuple, Type, Union

import pytest

from mountaineer.client_builder.interface_builders.enum import EnumInterface
from mountaineer.client_builder.parser import EnumWrapper


# Basic Enums
class StringEnum(Enum):
    ALPHA: str = "alpha"
    BETA: str = "beta"
    GAMMA: str = "gamma"


class NumberEnum(Enum):
    ONE: int = 1
    TWO: int = 2
    THREE: int = 3


class MixedEnum(Enum):
    STRING: str = "value"
    NUMBER: int = 42
    BOOLEAN: bool = True
    NULL: None = None


class AutoEnum(Enum):
    FIRST = auto()
    SECOND = auto()
    THIRD = auto()


# Complex Value Enums
class ComplexEnum(Enum):
    DICT: Dict[str, str] = {"key": "value"}
    LIST: List[int] = [1, 2, 3]
    TUPLE: Tuple[int, str] = (1, "two")


# Edge Case Enums
class SingleEnum(Enum):
    ONLY: str = "only"


class DuplicateValueEnum(Enum):
    A: str = "value"
    B: str = "value"
    C: str = "value"


class SpecialCharEnum(Enum):
    DASH_VALUE: str = "dash-value"
    UNDERSCORE_VALUE: str = "underscore_value"
    SPACE_VALUE: str = "space value"


# Test Fixtures
@pytest.fixture
def string_enum_wrapper() -> EnumWrapper:
    return EnumWrapper(
        name=StringEnum.__name__, module_name=StringEnum.__module__, enum=StringEnum
    )


@pytest.fixture
def number_enum_wrapper() -> EnumWrapper:
    return EnumWrapper(
        name=NumberEnum.__name__, module_name=NumberEnum.__module__, enum=NumberEnum
    )


@pytest.fixture
def mixed_enum_wrapper() -> EnumWrapper:
    return EnumWrapper(
        name=MixedEnum.__name__, module_name=MixedEnum.__module__, enum=MixedEnum
    )


class TestBasicEnumGeneration:
    def test_string_enum(self, string_enum_wrapper: EnumWrapper) -> None:
        interface: EnumInterface = EnumInterface.from_enum(string_enum_wrapper)
        ts_code: str = interface.to_js()

        assert "export enum StringEnum" in ts_code
        assert "ALPHA = " in ts_code
        assert '"alpha"' in ts_code
        assert ts_code.count(",") == 2  # Two commas for three values

    def test_number_enum(self, number_enum_wrapper: EnumWrapper) -> None:
        interface: EnumInterface = EnumInterface.from_enum(number_enum_wrapper)
        ts_code: str = interface.to_js()

        assert "ONE = 1" in ts_code
        assert "TWO = 2" in ts_code
        assert "THREE = 3" in ts_code

    def test_mixed_type_enum(self, mixed_enum_wrapper: EnumWrapper) -> None:
        interface: EnumInterface = EnumInterface.from_enum(mixed_enum_wrapper)
        ts_code: str = interface.to_js()

        assert '"value"' in ts_code  # String value
        assert "42" in ts_code  # Number value
        assert "true" in ts_code  # Boolean value
        assert "null" in ts_code  # Null value


class TestEnumFormatting:
    def test_export_statement(self, string_enum_wrapper: EnumWrapper) -> None:
        interface: EnumInterface = EnumInterface.from_enum(string_enum_wrapper)

        # Test with export
        assert interface.to_js().startswith("export enum")

        # Test without export
        interface.include_export = False
        assert interface.to_js().startswith("enum")
        assert "export" not in interface.to_js()

    def test_enum_structure(self, string_enum_wrapper: EnumWrapper) -> None:
        interface: EnumInterface = EnumInterface.from_enum(string_enum_wrapper)
        ts_code: str = interface.to_js()

        # Check basic structure
        assert ts_code.count("{") == 1
        assert ts_code.count("}") == 1
        assert ts_code.count(",") == len(StringEnum) - 1

    @pytest.mark.parametrize(
        "value,expected",
        [
            ('"string"', "string"),
            ("42", 42),
            ("true", True),
            ("null", None),
        ],
    )
    def test_value_formatting(
        self, value: str, expected: Union[str, int, bool, None]
    ) -> None:
        class ValueEnum(Enum):
            TEST = expected

        wrapper: EnumWrapper = EnumWrapper("ValueEnum", ValueEnum.__module__, ValueEnum)
        interface: EnumInterface = EnumInterface.from_enum(wrapper)
        ts_code: str = interface.to_js()

        assert f"TEST = {value}" in ts_code


class TestComplexCases:
    def test_auto_enum(self) -> None:
        wrapper: EnumWrapper = EnumWrapper("AutoEnum", AutoEnum.__module__, AutoEnum)
        interface: EnumInterface = EnumInterface.from_enum(wrapper)
        ts_code: str = interface.to_js()

        # Auto values should be converted to sequential numbers
        assert "FIRST = 1" in ts_code
        assert "SECOND = 2" in ts_code
        assert "THIRD = 3" in ts_code

    def test_complex_values(self) -> None:
        wrapper: EnumWrapper = EnumWrapper(
            "ComplexEnum", ComplexEnum.__module__, ComplexEnum
        )
        interface: EnumInterface = EnumInterface.from_enum(wrapper)
        ts_code: str = interface.to_js()

        # Complex values should be stringified
        assert "DICT = " in ts_code
        assert "LIST = " in ts_code
        assert "TUPLE = " in ts_code
        assert "{" in ts_code  # Dict representation
        assert "[" in ts_code  # List representation

    def test_duplicate_values(self) -> None:
        wrapper: EnumWrapper = EnumWrapper(
            "DuplicateValueEnum", DuplicateValueEnum.__module__, DuplicateValueEnum
        )
        interface: EnumInterface = EnumInterface.from_enum(wrapper)
        ts_code: str = interface.to_js()

        # All members should be present despite duplicate values
        assert "A = " in ts_code
        assert "B = " in ts_code
        assert "C = " in ts_code
        assert ts_code.count('"value"') == 3


class TestEdgeCases:
    def test_single_member_enum(self) -> None:
        wrapper: EnumWrapper = EnumWrapper(
            "SingleEnum", SingleEnum.__module__, SingleEnum
        )
        interface: EnumInterface = EnumInterface.from_enum(wrapper)
        ts_code: str = interface.to_js()

        assert "ONLY = " in ts_code
        assert ts_code.count(",") == 0  # No commas needed for single member

    def test_special_characters(self) -> None:
        wrapper: EnumWrapper = EnumWrapper(
            "SpecialCharEnum", SpecialCharEnum.__module__, SpecialCharEnum
        )
        interface: EnumInterface = EnumInterface.from_enum(wrapper)
        ts_code: str = interface.to_js()

        assert "DASH_VALUE = " in ts_code
        assert "UNDERSCORE_VALUE = " in ts_code
        assert "SPACE_VALUE = " in ts_code
        assert "-" in ts_code
        assert "_" in ts_code
        assert " " in ts_code

    def test_empty_enum(self) -> None:
        class EmptyEnum(Enum):
            pass

        wrapper: EnumWrapper = EnumWrapper("EmptyEnum", EmptyEnum.__module__, EmptyEnum)
        interface: EnumInterface = EnumInterface.from_enum(wrapper)
        ts_code: str = interface.to_js()

        assert "enum EmptyEnum {" in ts_code
        assert ts_code.strip().endswith("}")

    @pytest.mark.parametrize(
        "enum_name",
        [
            "interface",  # TypeScript keyword
            "type",  # TypeScript keyword
            "enum",  # TypeScript keyword
            "my_enum",  # Underscore
            "MyEnum2",  # Number
        ],
    )
    def test_enum_naming(self, enum_name: str) -> None:
        # Dynamically create enum
        enum_type: Type[Enum] = type(enum_name, (Enum,), {"MEMBER": "value"})
        wrapper: EnumWrapper = EnumWrapper(enum_name, enum_type.__module__, enum_type)
        interface: EnumInterface = EnumInterface.from_enum(wrapper)

        ts_code: str = interface.to_js()
        assert f"enum {enum_name}" in ts_code
