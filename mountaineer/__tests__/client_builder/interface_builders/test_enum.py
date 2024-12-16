from enum import Enum, auto
from typing import Union

import pytest

from mountaineer.__tests__.client_builder.interface_builders.common import (
    create_enum_wrapper,
)
from mountaineer.client_builder.interface_builders.enum import EnumInterface


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
        assert "'alpha'" in ts_code
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

        assert "'value'" in ts_code
        assert "42" in ts_code
        assert "true" in ts_code
        assert "null" in ts_code


class TestEnumFormatting:
    def test_export_statement(self):
        class ExampleEnum(Enum):
            A = "a"
            B = "b"

        interface = EnumInterface.from_enum(create_enum_wrapper(ExampleEnum))

        # Test with export
        assert interface.to_js().startswith("export enum")

        # Test without export
        interface.include_export = False
        assert interface.to_js().startswith("enum")
        assert "export" not in interface.to_js()

    def test_enum_structure(self):
        class ExampleEnum(Enum):
            A = "a"
            B = "b"
            C = "c"

        interface = EnumInterface.from_enum(create_enum_wrapper(ExampleEnum))
        ts_code = interface.to_js()

        assert ts_code.count("{") == 1
        assert ts_code.count("}") == 1
        assert ts_code.count(",") == len(ExampleEnum) - 1

    @pytest.mark.parametrize(
        "value, expected",
        [
            ("string", "'string'"),
            (42, "42"),
            (True, "true"),
            (None, "null"),
        ],
    )
    def test_value_formatting(self, value: str, expected: Union[str, int, bool, None]):
        class ValueEnum(Enum):
            TEST = value

        interface = EnumInterface.from_enum(create_enum_wrapper(ValueEnum))
        ts_code = interface.to_js()

        assert f"TEST = {expected}" in ts_code


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
        assert ts_code.count("'value'") == 3


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

        assert "DASH_VALUE = 'dash-value'" in ts_code
        assert "UNDERSCORE_VALUE = 'underscore_value'" in ts_code
        assert "SPACE_VALUE = 'space value'" in ts_code

    def test_empty_enum(self):
        class EmptyEnum(Enum):
            pass

        interface = EnumInterface.from_enum(create_enum_wrapper(EmptyEnum))
        ts_code = interface.to_js()

        assert "enum EmptyEnum {" in ts_code
        assert ts_code.strip().endswith("}")
