from enum import Enum, auto
from typing import Type, Union

import pytest

from mountaineer.client_builder.interface_builders.enum import EnumInterface
from mountaineer.client_builder.parser import EnumWrapper, WrapperName


def create_enum_wrapper(enum_class: Type[Enum]) -> EnumWrapper:
    """Helper function to create enum wrappers"""
    wrapper_name = WrapperName(enum_class.__name__)
    return EnumWrapper(name=wrapper_name, module_name="test_module", enum=enum_class)


class TestBasicEnumGeneration:
    def test_string_enum(self):
        class StringEnum(Enum):
            ALPHA = "alpha"
            BETA = "beta"
            GAMMA = "gamma"

        interface = EnumInterface.from_enum(create_enum_wrapper(StringEnum))
        ts_code = interface.to_js()

        assert "export enum StringEnum" in ts_code
        assert "ALPHA = " in ts_code
        assert '"alpha"' in ts_code
        assert ts_code.count(",") == 2  # Two commas for three values

    def test_number_enum(self):
        class NumberEnum(Enum):
            ONE = 1
            TWO = 2
            THREE = 3

        interface = EnumInterface.from_enum(create_enum_wrapper(NumberEnum))
        ts_code = interface.to_js()

        assert "ONE = 1" in ts_code
        assert "TWO = 2" in ts_code
        assert "THREE = 3" in ts_code

    def test_mixed_type_enum(self):
        class MixedEnum(Enum):
            STRING = "value"
            NUMBER = 42
            BOOLEAN = True
            NULL = None

        interface = EnumInterface.from_enum(create_enum_wrapper(MixedEnum))
        ts_code = interface.to_js()

        assert '"value"' in ts_code
        assert "42" in ts_code
        assert "true" in ts_code
        assert "null" in ts_code


class TestEnumFormatting:
    def test_export_statement(self):
        class TestEnum(Enum):
            A = "a"
            B = "b"

        interface = EnumInterface.from_enum(create_enum_wrapper(TestEnum))

        # Test with export
        assert interface.to_js().startswith("export enum")

        # Test without export
        interface.include_export = False
        assert interface.to_js().startswith("enum")
        assert "export" not in interface.to_js()

    def test_enum_structure(self):
        class TestEnum(Enum):
            A = "a"
            B = "b"
            C = "c"

        interface = EnumInterface.from_enum(create_enum_wrapper(TestEnum))
        ts_code = interface.to_js()

        assert ts_code.count("{") == 1
        assert ts_code.count("}") == 1
        assert ts_code.count(",") == len(TestEnum) - 1

    @pytest.mark.parametrize(
        "value,expected",
        [
            ('"string"', "string"),
            ("42", 42),
            ("true", True),
            ("null", None),
        ],
    )
    def test_value_formatting(self, value: str, expected: Union[str, int, bool, None]):
        class ValueEnum(Enum):
            TEST = expected

        interface = EnumInterface.from_enum(create_enum_wrapper(ValueEnum))
        ts_code = interface.to_js()

        assert f"TEST = {value}" in ts_code


class TestComplexCases:
    def test_auto_enum(self):
        class AutoEnum(Enum):
            FIRST = auto()
            SECOND = auto()
            THIRD = auto()

        interface = EnumInterface.from_enum(create_enum_wrapper(AutoEnum))
        ts_code = interface.to_js()

        assert "FIRST = 1" in ts_code
        assert "SECOND = 2" in ts_code
        assert "THIRD = 3" in ts_code

    def test_complex_values(self):
        class ComplexEnum(Enum):
            DICT = {"key": "value"}
            LIST = [1, 2, 3]
            TUPLE = (1, "two")

        interface = EnumInterface.from_enum(create_enum_wrapper(ComplexEnum))
        ts_code = interface.to_js()

        assert "DICT = " in ts_code
        assert "LIST = " in ts_code
        assert "TUPLE = " in ts_code
        assert "{" in ts_code  # Dict representation
        assert "[" in ts_code  # List representation

    def test_duplicate_values(self):
        class DuplicateValueEnum(Enum):
            A = "value"
            B = "value"
            C = "value"

        interface = EnumInterface.from_enum(create_enum_wrapper(DuplicateValueEnum))
        ts_code = interface.to_js()

        assert "A = " in ts_code
        assert "B = " in ts_code
        assert "C = " in ts_code
        assert ts_code.count('"value"') == 3


class TestEdgeCases:
    def test_single_member_enum(self):
        class SingleEnum(Enum):
            ONLY = "only"

        interface = EnumInterface.from_enum(create_enum_wrapper(SingleEnum))
        ts_code = interface.to_js()

        assert "ONLY = " in ts_code
        assert ts_code.count(",") == 0

    def test_special_characters(self):
        class SpecialCharEnum(Enum):
            DASH_VALUE = "dash-value"
            UNDERSCORE_VALUE = "underscore_value"
            SPACE_VALUE = "space value"

        interface = EnumInterface.from_enum(create_enum_wrapper(SpecialCharEnum))
        ts_code = interface.to_js()

        assert "DASH_VALUE = " in ts_code
        assert "UNDERSCORE_VALUE = " in ts_code
        assert "SPACE_VALUE = " in ts_code
        assert "-" in ts_code
        assert "_" in ts_code
        assert " " in ts_code

    def test_empty_enum(self):
        class EmptyEnum(Enum):
            pass

        interface = EnumInterface.from_enum(create_enum_wrapper(EmptyEnum))
        ts_code = interface.to_js()

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
    def test_enum_naming(self, enum_name: str):
        # Dynamically create enum
        enum_type = type(enum_name, (Enum,), {"MEMBER": "value"})
        interface = EnumInterface.from_enum(create_enum_wrapper(enum_type))
        ts_code = interface.to_js()

        assert f"enum {enum_name}" in ts_code

    def test_non_string_keys(self):
        class ComplexKeyEnum(Enum):
            _PRIVATE = "private"
            DASH_KEY = "dash"
            SPACE_KEY = "space"

        interface = EnumInterface.from_enum(create_enum_wrapper(ComplexKeyEnum))
        ts_code = interface.to_js()

        assert "_PRIVATE = " in ts_code
        assert "DASH_KEY = " in ts_code
        assert "SPACE_KEY = " in ts_code

    def test_enum_value_serialization(self):
        class SerializationEnum(Enum):
            DICT = {"complex": {"nested": True}}
            LIST = [{"item": 1}, {"item": 2}]
            MIXED = (1, "two", [3, 4], {"five": 6})

        interface = EnumInterface.from_enum(create_enum_wrapper(SerializationEnum))
        ts_code = interface.to_js()

        # Verify complex values are properly stringified
        assert '"complex"' in ts_code
        assert '"nested"' in ts_code
        assert '"item"' in ts_code
        assert '"five"' in ts_code
