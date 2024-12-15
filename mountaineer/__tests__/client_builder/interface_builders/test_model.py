from datetime import datetime
from enum import Enum
from typing import Any, Type

import pytest
from pydantic import BaseModel

from mountaineer.__tests__.client_builder.interface_builders.common import (
    create_field_wrapper,
    create_model_wrapper,
)
from mountaineer.__tests__.client_builder.interface_builders.test_enum import (
    create_enum_wrapper,
)
from mountaineer.client_builder.interface_builders.model import ModelInterface
from mountaineer.client_builder.types import Or


class TestBasicInterfaceGeneration:
    def test_simple_model_interface(self):
        class FieldType(Enum):
            STRING = "string"
            NUMBER = "number"

        wrapper = create_model_wrapper(
            BaseModel,
            "SimpleModel",
            [
                create_field_wrapper("string_field", str),
                create_field_wrapper("int_field", int),
                create_field_wrapper("optional_field", Or(str, None), required=False),
                create_field_wrapper("enum_field", create_enum_wrapper(FieldType)),
            ],
        )

        interface = ModelInterface.from_model(wrapper)
        ts_code = interface.to_js()

        assert "export interface SimpleModel" in ts_code
        assert "string_field: string" in ts_code
        assert "int_field: number" in ts_code
        assert "optional_field?: string" in ts_code
        assert "enum_field: FieldType" in ts_code

    def test_no_export(self):
        wrapper = create_model_wrapper(
            BaseModel, "SimpleModel", [create_field_wrapper("field", str)]
        )

        interface = ModelInterface.from_model(wrapper)
        interface.include_export = False
        ts_code = interface.to_js()

        assert not ts_code.startswith("export")
        assert ts_code.startswith("interface SimpleModel")

    @pytest.mark.parametrize(
        "field_name,field_type,expected_ts",
        [
            ("string_field", str, "string"),
            ("int_field", int, "number"),
            ("bool_field", bool, "boolean"),
            ("float_field", float, "number"),
            ("date_field", datetime, "string"),
        ],
    )
    def test_field_type_conversion(
        self, field_name: str, field_type: Type[Any], expected_ts: str
    ):
        wrapper = create_model_wrapper(
            BaseModel, "DynamicModel", [create_field_wrapper(field_name, field_type)]
        )

        interface = ModelInterface.from_model(wrapper)
        assert f"{field_name}: {expected_ts}" in interface.to_js()


class TestInheritanceHandling:
    def test_single_inheritance(self):
        parent_wrapper = create_model_wrapper(
            BaseModel,
            "ParentModel",
            [
                create_field_wrapper("parent_field", str),
                create_field_wrapper("shared_field", int),
            ],
        )

        child_wrapper = create_model_wrapper(
            BaseModel,
            "ChildModel",
            [
                create_field_wrapper("child_field", bool),
                create_field_wrapper("shared_field", float),  # Override type
            ],
            superclasses=[parent_wrapper],
        )

        interface = ModelInterface.from_model(child_wrapper)
        ts_code = interface.to_js()

        assert "interface ChildModel extends ParentModel" in ts_code
        assert "child_field: boolean" in ts_code
        assert "shared_field: number" in ts_code

    def test_multiple_inheritance(self):
        base1_wrapper = create_model_wrapper(
            BaseModel, "MultiInheritBase1", [create_field_wrapper("base1_field", str)]
        )

        base2_wrapper = create_model_wrapper(
            BaseModel, "MultiInheritBase2", [create_field_wrapper("base2_field", int)]
        )

        child_wrapper = create_model_wrapper(
            BaseModel,
            "MultiInheritChild",
            [create_field_wrapper("child_field", bool)],
            superclasses=[base1_wrapper, base2_wrapper],
        )

        interface = ModelInterface.from_model(child_wrapper)
        ts_code = interface.to_js()

        assert "extends MultiInheritBase1, MultiInheritBase2" in ts_code
        assert "child_field: boolean" in ts_code


class TestEdgeCases:
    def test_empty_model(self):
        wrapper = create_model_wrapper(BaseModel, "EmptyModel", [])
        interface = ModelInterface.from_model(wrapper)
        ts_code = interface.to_js()

        assert "interface EmptyModel {\n\n}" in ts_code

    def test_all_optional_fields(self):
        wrapper = create_model_wrapper(
            BaseModel,
            "OptionalModel",
            [
                create_field_wrapper("field1", str, required=False),
                create_field_wrapper("field2", int, required=False),
            ],
        )

        interface = ModelInterface.from_model(wrapper)
        ts_code = interface.to_js()

        assert "field1?: string" in ts_code
        assert "field2?: number" in ts_code
