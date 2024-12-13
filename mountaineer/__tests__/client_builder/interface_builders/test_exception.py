from datetime import datetime
from typing import Any, Dict, List, Optional, Type

import pytest
from pydantic import BaseModel

from mountaineer.client_builder.interface_builders.exception import ExceptionInterface
from mountaineer.client_builder.parser import ExceptionWrapper, WrapperName
from mountaineer.exceptions import APIException


# Base Models for Exception Fields
class ErrorDetail(BaseModel):
    code: str
    description: str


class ValidationError(BaseModel):
    field: str
    message: str


# Exception Definitions
class SimpleException(APIException):
    status_code: int = 400

    class InternalModel(BaseModel):
        message: str
        code: int


class OptionalFieldsException(APIException):
    status_code: int = 400

    class InternalModel(BaseModel):
        message: str
        details: Optional[str] = None
        timestamp: Optional[datetime] = None


class ComplexException(APIException):
    status_code: int = 500

    class InternalModel(BaseModel):
        data: Dict[str, Any]
        errors: List[ValidationError]
        details: ErrorDetail


class NestedException(APIException):
    status_code: int = 400

    class InternalModel(BaseModel):
        outer: Dict[str, List[ErrorDetail]]
        meta: Optional[Dict[str, str]] = None


# Fixtures
@pytest.fixture
def simple_exception_wrapper() -> ExceptionWrapper:
    return ExceptionWrapper(
        name=WrapperName("SimpleException"),
        module_name=SimpleException.__module__,
        status_code=SimpleException.status_code,
        exception=SimpleException,
        value_models=[
            {"name": "message", "value": str, "required": True},
            {"name": "code", "value": int, "required": True},
        ],
    )


@pytest.fixture
def optional_fields_wrapper() -> ExceptionWrapper:
    return ExceptionWrapper(
        name=WrapperName("OptionalFieldsException"),
        module_name=OptionalFieldsException.__module__,
        status_code=OptionalFieldsException.status_code,
        exception=OptionalFieldsException,
        value_models=[
            {"name": "message", "value": str, "required": True},
            {"name": "details", "value": str, "required": False},
            {"name": "timestamp", "value": datetime, "required": False},
        ],
    )


@pytest.fixture
def complex_exception_wrapper() -> ExceptionWrapper:
    return ExceptionWrapper(
        name=WrapperName("ComplexException"),
        module_name=ComplexException.__module__,
        status_code=ComplexException.status_code,
        exception=ComplexException,
        value_models=[
            {"name": "data", "value": Dict[str, Any], "required": True},
            {"name": "errors", "value": List[ValidationError], "required": True},
            {"name": "details", "value": ErrorDetail, "required": True},
        ],
    )


class TestBasicGeneration:
    def test_simple_exception(self, simple_exception_wrapper: ExceptionWrapper) -> None:
        interface: ExceptionInterface = ExceptionInterface.from_exception(
            simple_exception_wrapper
        )
        ts_code: str = interface.to_js()

        assert "export interface SimpleException" in ts_code
        assert "message: string" in ts_code
        assert "code: number" in ts_code

    def test_optional_fields(self, optional_fields_wrapper: ExceptionWrapper) -> None:
        interface: ExceptionInterface = ExceptionInterface.from_exception(
            optional_fields_wrapper
        )
        ts_code: str = interface.to_js()

        assert "message: string" in ts_code
        assert "details?: string" in ts_code
        assert "timestamp?: string" in ts_code  # datetime converts to string

    def test_complex_fields(self, complex_exception_wrapper: ExceptionWrapper) -> None:
        interface: ExceptionInterface = ExceptionInterface.from_exception(
            complex_exception_wrapper
        )
        ts_code: str = interface.to_js()

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
            (Dict[str, str], "Record<string, string>"),
            (List[int], "Array<number>"),
        ],
    )
    def test_type_conversion(
        self, field_type: Type[Any], expected_ts_type: str
    ) -> None:
        class TypeException(APIException):
            status_code: int = 400

            class InternalModel(BaseModel):
                field: field_type

        wrapper: ExceptionWrapper = ExceptionWrapper(
            name=WrapperName("TypeException"),
            module_name=TypeException.__module__,
            status_code=TypeException.status_code,
            exception=TypeException,
            value_models=[{"name": "field", "value": field_type, "required": True}],
        )

        interface: ExceptionInterface = ExceptionInterface.from_exception(wrapper)
        assert expected_ts_type in interface.to_js()


class TestOutputFormatting:
    def test_export_control(self, simple_exception_wrapper: ExceptionWrapper) -> None:
        interface: ExceptionInterface = ExceptionInterface.from_exception(
            simple_exception_wrapper
        )

        # With export
        assert interface.to_js().startswith("export")

        # Without export
        interface.include_export = False
        assert not interface.to_js().startswith("export")

    def test_interface_structure(
        self, simple_exception_wrapper: ExceptionWrapper
    ) -> None:
        interface: ExceptionInterface = ExceptionInterface.from_exception(
            simple_exception_wrapper
        )
        ts_code: str = interface.to_js()

        # Check basic structure
        assert ts_code.startswith("export interface")
        assert "{" in ts_code
        assert "}" in ts_code
        assert ts_code.count("{") == ts_code.count("}")


class TestEdgeCases:
    def test_empty_exception(self) -> None:
        class EmptyException(APIException):
            status_code: int = 400

            class InternalModel(BaseModel):
                pass

        wrapper: ExceptionWrapper = ExceptionWrapper(
            name=WrapperName("EmptyException"),
            module_name=EmptyException.__module__,
            status_code=EmptyException.status_code,
            exception=EmptyException,
            value_models=[],
        )

        interface: ExceptionInterface = ExceptionInterface.from_exception(wrapper)
        ts_code: str = interface.to_js()

        assert "interface EmptyException {" in ts_code
        assert ts_code.strip().endswith("}")

    def test_nested_structure(self) -> None:
        wrapper: ExceptionWrapper = ExceptionWrapper(
            name=WrapperName("NestedException"),
            module_name=NestedException.__module__,
            status_code=NestedException.status_code,
            exception=NestedException,
            value_models=[
                {
                    "name": "outer",
                    "value": Dict[str, List[ErrorDetail]],
                    "required": True,
                },
                {"name": "meta", "value": Optional[Dict[str, str]], "required": False},
            ],
        )

        interface: ExceptionInterface = ExceptionInterface.from_exception(wrapper)
        ts_code: str = interface.to_js()

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
    def test_typescript_keywords(self, name: str) -> None:
        class GenericException(APIException):
            status_code: int = 400

            class InternalModel(BaseModel):
                field: str

        wrapper: ExceptionWrapper = ExceptionWrapper(
            name=WrapperName(name),
            module_name=GenericException.__module__,
            status_code=GenericException.status_code,
            exception=GenericException,
            value_models=[{"name": "field", "value": str, "required": True}],
        )

        interface: ExceptionInterface = ExceptionInterface.from_exception(wrapper)
        ts_code: str = interface.to_js()

        assert f"interface {name}" in ts_code
        assert "field: string" in ts_code

    def test_all_optional_fields(self) -> None:
        class OptionalException(APIException):
            status_code: int = 400

            class InternalModel(BaseModel):
                field1: Optional[str] = None
                field2: Optional[int] = None

        wrapper: ExceptionWrapper = ExceptionWrapper(
            name=WrapperName("OptionalException"),
            module_name=OptionalException.__module__,
            status_code=OptionalException.status_code,
            exception=OptionalException,
            value_models=[
                {"name": "field1", "value": str, "required": False},
                {"name": "field2", "value": int, "required": False},
            ],
        )

        interface: ExceptionInterface = ExceptionInterface.from_exception(wrapper)
        ts_code: str = interface.to_js()

        assert "field1?: string" in ts_code
        assert "field2?: number" in ts_code
