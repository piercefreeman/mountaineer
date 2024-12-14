from datetime import datetime
from enum import Enum
from typing import Any, Literal, Optional, Type, Union

import pytest
from pydantic import BaseModel

from mountaineer.client_builder.interface_builders.model import ModelInterface
from mountaineer.client_builder.parser import FieldWrapper, ModelWrapper, WrapperName


def create_field_wrapper(
    name: str, type_hint: Type, required: bool = True
) -> FieldWrapper:
    return FieldWrapper(name=name, value=type_hint, required=required)


def create_model_wrapper(
    name: str, fields: list[FieldWrapper], superclasses: list["ModelWrapper"] = None
) -> ModelWrapper:
    wrapper_name = WrapperName(name)
    return ModelWrapper(
        name=wrapper_name,
        module_name="test_module",
        model=BaseModel,  # Base class is sufficient for testing
        isolated_model=BaseModel,
        superclasses=superclasses or [],
        value_models=fields,
    )


class TestBasicInterfaceGeneration:
    def test_simple_model_interface(self):
        class FieldType(Enum):
            STRING = "string"
            NUMBER = "number"

        wrapper = create_model_wrapper(
            "SimpleModel",
            [
                create_field_wrapper("string_field", str),
                create_field_wrapper("int_field", int),
                create_field_wrapper("optional_field", Optional[str], required=False),
                create_field_wrapper("enum_field", FieldType),
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
            "SimpleModel", [create_field_wrapper("field", str)]
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
            "DynamicModel", [create_field_wrapper(field_name, field_type)]
        )

        interface = ModelInterface.from_model(wrapper)
        assert f"{field_name}: {expected_ts}" in interface.to_js()


class TestInheritanceHandling:
    def test_single_inheritance(self):
        parent_wrapper = create_model_wrapper(
            "ParentModel",
            [
                create_field_wrapper("parent_field", str),
                create_field_wrapper("shared_field", int),
            ],
        )

        child_wrapper = create_model_wrapper(
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
            "MultiInheritBase1", [create_field_wrapper("base1_field", str)]
        )

        base2_wrapper = create_model_wrapper(
            "MultiInheritBase2", [create_field_wrapper("base2_field", int)]
        )

        child_wrapper = create_model_wrapper(
            "MultiInheritChild",
            [create_field_wrapper("child_field", bool)],
            superclasses=[base1_wrapper, base2_wrapper],
        )

        interface = ModelInterface.from_model(child_wrapper)
        ts_code = interface.to_js()

        assert "extends MultiInheritBase1, MultiInheritBase2" in ts_code
        assert "child_field: boolean" in ts_code


class TestComplexTypeHandling:
    def test_nested_model_interface(self):
        simple_wrapper = create_model_wrapper(
            "SimpleModel", [create_field_wrapper("field", str)]
        )

        nested_wrapper = create_model_wrapper(
            "NestedModel",
            [
                create_field_wrapper("regular_field", str),
                create_field_wrapper("simple", simple_wrapper.model),
                create_field_wrapper(
                    "optional_simple", Optional[simple_wrapper.model], required=False
                ),
                create_field_wrapper("list_simple", list[simple_wrapper.model]),
                create_field_wrapper("dict_simple", dict[str, simple_wrapper.model]),
            ],
        )

        interface = ModelInterface.from_model(nested_wrapper)
        ts_code = interface.to_js()

        assert "simple: SimpleModel" in ts_code
        assert "optional_simple?: SimpleModel" in ts_code
        assert "list_simple: Array<SimpleModel>" in ts_code
        assert "dict_simple: Record<string, SimpleModel>" in ts_code


class TestEdgeCases:
    def test_empty_model(self):
        wrapper = create_model_wrapper("EmptyModel", [])
        interface = ModelInterface.from_model(wrapper)
        ts_code = interface.to_js()

        assert "interface EmptyModel {}" in ts_code

    def test_all_optional_fields(self):
        wrapper = create_model_wrapper(
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

    def test_union_types(self):
        wrapper = create_model_wrapper(
            "UnionModel",
            [
                create_field_wrapper("union_field", Union[str, int]),
                create_field_wrapper(
                    "optional_union", Optional[Union[bool, float]], required=False
                ),
            ],
        )

        interface = ModelInterface.from_model(wrapper)
        ts_code = interface.to_js()

        assert "union_field: string | number" in ts_code
        assert "optional_union?: boolean | number" in ts_code

    def test_literal_types(self):
        wrapper = create_model_wrapper(
            "LiteralModel",
            [create_field_wrapper("status", Literal["active", "inactive"])],
        )

        interface = ModelInterface.from_model(wrapper)
        ts_code = interface.to_js()

        assert 'status: "active" | "inactive"' in ts_code

    def test_complex_nested_types(self):
        wrapper = create_model_wrapper(
            "ComplexModel",
            [
                create_field_wrapper(
                    "nested_lists", list[dict[str, list[Union[str, int]]]]
                ),
                create_field_wrapper(
                    "optional_complex",
                    Optional[dict[str, list[dict[str, Any]]]],
                    required=False,
                ),
            ],
        )

        interface = ModelInterface.from_model(wrapper)
        ts_code = interface.to_js()

        assert "Array<Record<string, Array<string | number>>>" in ts_code
        assert "Record<string, Array<Record<string, any>>>?" in ts_code


class TestAnnotationConversion:
    @pytest.mark.parametrize(
        "python_type,expected_ts",
        [
            (list[str], "Array<string>"),
            (dict[str, int], "Record<string, number>"),
            (Optional[str], "string | undefined"),
            (Union[int, str, bool], "number | string | boolean"),
            (list[dict[str, int]], "Array<Record<string, number>>"),
        ],
    )
    def test_annotation_conversion(self, python_type: Type[Any], expected_ts: str):
        wrapper = create_model_wrapper(
            "AnnotationModel", [create_field_wrapper("field", python_type)]
        )

        interface = ModelInterface.from_model(wrapper)
        ts_code = interface.to_js()

        # Remove spaces for consistent comparison
        ts_code_normalized = "".join(ts_code.split())
        expected_ts_normalized = "".join(expected_ts.split())

        assert expected_ts_normalized in ts_code_normalized
