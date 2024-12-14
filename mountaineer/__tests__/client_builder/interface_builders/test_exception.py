from datetime import datetime
from typing import Any, Optional, Type, dict, list

import pytest
from pydantic import BaseModel

from mountaineer.client_builder.interface_builders.exception import ExceptionInterface
from mountaineer.client_builder.parser import (
    ExceptionWrapper,
    FieldWrapper,
    WrapperName,
)
from mountaineer.exceptions import APIException


# Helper function to create field wrappers
def create_field_wrapper(
    name: str, type_hint: Type, required: bool = True
) -> FieldWrapper:
    return FieldWrapper(name=name, value=type_hint, required=required)


# Helper function to create exception wrappers
def create_exception_wrapper(
    name: str, status_code: int, value_models: list[FieldWrapper]
) -> ExceptionWrapper:
    wrapper_name = WrapperName(name)
    return ExceptionWrapper(
        name=wrapper_name,
        module_name="test_module",
        status_code=status_code,
        exception=APIException,  # Base class is sufficient for testing
        value_models=value_models,
    )


class TestBasicGeneration:
    def test_simple_exception(self):
        wrapper = create_exception_wrapper(
            "SimpleException",
            400,
            [create_field_wrapper("message", str), create_field_wrapper("code", int)],
        )

        interface = ExceptionInterface.from_exception(wrapper)
        ts_code = interface.to_js()

        assert "export interface SimpleException" in ts_code
        assert "message: string" in ts_code
        assert "code: number" in ts_code

    def test_optional_fields(self):
        wrapper = create_exception_wrapper(
            "OptionalFieldsException",
            400,
            [
                create_field_wrapper("message", str),
                create_field_wrapper("details", str, required=False),
                create_field_wrapper("timestamp", datetime, required=False),
            ],
        )

        interface = ExceptionInterface.from_exception(wrapper)
        ts_code = interface.to_js()

        assert "message: string" in ts_code
        assert "details?: string" in ts_code
        assert "timestamp?: string" in ts_code  # datetime converts to string

    def test_complex_fields(self):
        class ValidationError(BaseModel):
            field: str
            message: str

        class ErrorDetail(BaseModel):
            code: str
            description: str

        wrapper = create_exception_wrapper(
            "ComplexException",
            500,
            [
                create_field_wrapper("data", dict[str, Any]),
                create_field_wrapper("errors", list[ValidationError]),
                create_field_wrapper("details", ErrorDetail),
            ],
        )

        interface = ExceptionInterface.from_exception(wrapper)
        ts_code = interface.to_js()

        assert "data: Record<string, any>" in ts_code
        assert "errors: Array<ValidationError>" in ts_code
        assert "details: ErrorDetail" in ts_code


class TestFieldTypeConversion:
    @pytest.mark.parametrize(
        "field_type,expected_ts_type",
        [
            (str, "string"),
            (int, "number"),
            (bool, "boolean"),
            (float, "number"),
            (datetime, "string"),
            (dict[str, str], "Record<string, string>"),
            (list[int], "Array<number>"),
        ],
    )
    def test_type_conversion(self, field_type: Type[Any], expected_ts_type: str):
        wrapper = create_exception_wrapper(
            "TypeException", 400, [create_field_wrapper("field", field_type)]
        )

        interface = ExceptionInterface.from_exception(wrapper)
        ts_code = interface.to_js()
        assert expected_ts_type in ts_code


class TestOutputFormatting:
    def test_export_control(self):
        wrapper = create_exception_wrapper(
            "SimpleException", 400, [create_field_wrapper("message", str)]
        )

        interface = ExceptionInterface.from_exception(wrapper)

        # With export
        assert interface.to_js().startswith("export")

        # Without export
        interface.include_export = False
        assert not interface.to_js().startswith("export")

    def test_interface_structure(self):
        wrapper = create_exception_wrapper(
            "SimpleException", 400, [create_field_wrapper("message", str)]
        )

        interface = ExceptionInterface.from_exception(wrapper)
        ts_code = interface.to_js()

        assert ts_code.startswith("export interface")
        assert "{" in ts_code
        assert "}" in ts_code
        assert ts_code.count("{") == ts_code.count("}")


class TestEdgeCases:
    def test_empty_exception(self):
        wrapper = create_exception_wrapper("EmptyException", 400, [])

        interface = ExceptionInterface.from_exception(wrapper)
        ts_code = interface.to_js()

        assert "interface EmptyException {" in ts_code
        assert ts_code.strip().endswith("}")

    def test_nested_structure(self):
        class ErrorDetail(BaseModel):
            code: str
            description: str

        wrapper = create_exception_wrapper(
            "NestedException",
            400,
            [
                create_field_wrapper("outer", dict[str, list[ErrorDetail]]),
                create_field_wrapper("meta", Optional[dict[str, str]], required=False),
            ],
        )

        interface = ExceptionInterface.from_exception(wrapper)
        ts_code = interface.to_js()

        assert "outer: Record<string, Array<ErrorDetail>>" in ts_code
        assert "meta?: Record<string, string>" in ts_code

    @pytest.mark.parametrize(
        "name",
        [
            "interface",  # TypeScript keyword
            "type",  # TypeScript keyword
            "class",  # TypeScript keyword
            "My_Error",  # Underscore
            "Error2",  # Number
        ],
    )
    def test_typescript_keywords(self, name: str):
        wrapper = create_exception_wrapper(
            name, 400, [create_field_wrapper("field", str)]
        )

        interface = ExceptionInterface.from_exception(wrapper)
        ts_code = interface.to_js()

        assert f"interface {name}" in ts_code
        assert "field: string" in ts_code

    def test_all_optional_fields(self):
        wrapper = create_exception_wrapper(
            "OptionalException",
            400,
            [
                create_field_wrapper("field1", str, required=False),
                create_field_wrapper("field2", int, required=False),
            ],
        )

        interface = ExceptionInterface.from_exception(wrapper)
        ts_code = interface.to_js()

        assert "field1?: string" in ts_code
        assert "field2?: number" in ts_code

    def test_complex_nested_types(self):
        wrapper = create_exception_wrapper(
            "ComplexNestedException",
            400,
            [
                create_field_wrapper(
                    "nested", dict[str, list[dict[str, Optional[list[str]]]]]
                ),
                create_field_wrapper("mixed", list[str | dict[str, Any] | list[int]]),
            ],
        )

        interface = ExceptionInterface.from_exception(wrapper)
        ts_code = interface.to_js()

        assert (
            "Record<string, Array<Record<string, Array<string> | undefined>>>"
            in ts_code
        )
        assert "Array<string | Record<string, any> | Array<number>>" in ts_code
