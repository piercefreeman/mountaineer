from datetime import datetime
from typing import Any, Type

import pytest
from pydantic import BaseModel

from mountaineer.__tests__.client_builder.interface_builders.common import (
    create_exception_wrapper,
    create_field_wrapper,
    create_model_wrapper,
)
from mountaineer.client_builder.interface_builders.exception import ExceptionInterface
from mountaineer.client_builder.types import DictOf, ListOf, Or
from mountaineer.exceptions import APIException


class TestBasicGeneration:
    def test_simple_exception(self):
        wrapper = create_exception_wrapper(
            APIException,
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
            APIException,
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
            APIException,
            "ComplexException",
            500,
            [
                create_field_wrapper("data", DictOf[str, Any]),
                create_field_wrapper(
                    "errors",
                    ListOf[create_model_wrapper(ValidationError, "ValidationError")],
                ),
                create_field_wrapper(
                    "details", create_model_wrapper(ErrorDetail, "ErrorDetail")
                ),
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
            (DictOf[str, str], "Record<string, string>"),
            (ListOf[int], "Array<number>"),
        ],
    )
    def test_type_conversion(self, field_type: Type[Any], expected_ts_type: str):
        wrapper = create_exception_wrapper(
            APIException,
            "TypeException",
            400,
            [create_field_wrapper("field", field_type)],
        )

        interface = ExceptionInterface.from_exception(wrapper)
        ts_code = interface.to_js()
        assert expected_ts_type in ts_code


class TestOutputFormatting:
    def test_export_control(self):
        wrapper = create_exception_wrapper(
            APIException, "SimpleException", 400, [create_field_wrapper("message", str)]
        )

        interface = ExceptionInterface.from_exception(wrapper)

        # With export
        assert interface.to_js().startswith("export")

        # Without export
        interface.include_export = False
        assert not interface.to_js().startswith("export")

    def test_interface_structure(self):
        wrapper = create_exception_wrapper(
            APIException, "SimpleException", 400, [create_field_wrapper("message", str)]
        )

        interface = ExceptionInterface.from_exception(wrapper)
        ts_code = interface.to_js()

        assert ts_code.startswith("export interface")
        assert "{" in ts_code
        assert "}" in ts_code
        assert ts_code.count("{") == ts_code.count("}")


class TestEdgeCases:
    def test_empty_exception(self):
        wrapper = create_exception_wrapper(APIException, "EmptyException", 400, [])

        interface = ExceptionInterface.from_exception(wrapper)
        ts_code = interface.to_js()

        assert "interface EmptyException {" in ts_code
        assert ts_code.strip().endswith("}")

    def test_nested_structure(self):
        class ErrorDetail(BaseModel):
            code: str
            description: str

        wrapper = create_exception_wrapper(
            APIException,
            "NestedException",
            400,
            [
                create_field_wrapper(
                    "outer",
                    DictOf[
                        str, ListOf[create_model_wrapper(ErrorDetail, "ErrorDetail")]
                    ],
                ),
                create_field_wrapper(
                    "meta", Or[DictOf[str, str], None], required=False
                ),
            ],
        )

        interface = ExceptionInterface.from_exception(wrapper)
        ts_code = interface.to_js()

        assert "outer: Record<string, Array<ErrorDetail>>" in ts_code
        assert "meta?: Record<string, string>" in ts_code

    def test_all_optional_fields(self):
        wrapper = create_exception_wrapper(
            APIException,
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
