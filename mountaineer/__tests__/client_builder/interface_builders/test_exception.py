from datetime import datetime
from typing import Any

from pydantic import BaseModel

from mountaineer.__tests__.client_builder.interface_builders.common import (
    create_exception_wrapper,
    create_field_wrapper,
    create_model_wrapper,
)
from mountaineer.client_builder.interface_builders.exception import ExceptionInterface
from mountaineer.client_builder.types import DictOf, ListOf
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
                create_field_wrapper("data", DictOf(str, Any)),
                create_field_wrapper(
                    "errors",
                    ListOf(create_model_wrapper(ValidationError, "ValidationError")),
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
