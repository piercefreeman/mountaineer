from datetime import datetime
from enum import Enum
from typing import Any, Dict, Generic, List, Literal, Optional, Type, TypeVar, Union

import pytest
from pydantic import BaseModel

from mountaineer.client_builder.interface_builders.model import ModelInterface
from mountaineer.client_builder.parser import ControllerParser, ModelWrapper

# Type variables for generic models
T = TypeVar("T")
S = TypeVar("S")


# Basic enum for testing
class FieldType(Enum):
    STRING: str = "string"
    NUMBER: str = "number"
    BOOLEAN: str = "boolean"


# Base test models
class SimpleModel(BaseModel):
    string_field: str
    int_field: int
    optional_field: Optional[str] = None
    enum_field: FieldType


class ParentModel(BaseModel):
    parent_field: str
    shared_field: int = 0


class ChildModel(ParentModel):
    child_field: bool
    shared_field: float  # Override type


class GenericModel(BaseModel, Generic[T]):
    value: T
    metadata: str


class NestedModel(BaseModel):
    regular_field: str
    simple: SimpleModel
    optional_simple: Optional[SimpleModel] = None
    list_simple: List[SimpleModel] = []
    dict_simple: Dict[str, SimpleModel] = {}
    generic: GenericModel[str]


# Forward reference model
class CircularModel(BaseModel):
    name: str
    parent: Optional["CircularModel"] = None


CircularModel.model_rebuild()


# Complex inheritance model
class MultiInheritBase1(BaseModel):
    base1_field: str


class MultiInheritBase2(BaseModel):
    base2_field: int


class MultiInheritChild(MultiInheritBase1, MultiInheritBase2):
    child_field: bool


# Fixtures
@pytest.fixture
def parser() -> ControllerParser:
    return ControllerParser()


@pytest.fixture
def simple_wrapper(parser: ControllerParser) -> ModelWrapper:
    return parser._parse_model(SimpleModel)


@pytest.fixture
def child_wrapper(parser: ControllerParser) -> ModelWrapper:
    return parser._parse_model(ChildModel)


@pytest.fixture
def nested_wrapper(parser: ControllerParser) -> ModelWrapper:
    return parser._parse_model(NestedModel)


@pytest.fixture
def multi_inherit_wrapper(parser: ControllerParser) -> ModelWrapper:
    return parser._parse_model(MultiInheritChild)


class TestBasicInterfaceGeneration:
    def test_simple_model_interface(self, simple_wrapper: ModelWrapper) -> None:
        interface: ModelInterface = ModelInterface.from_model(simple_wrapper)
        ts_code: str = interface.to_js()

        # Check basic structure
        assert "export interface SimpleModel" in ts_code
        assert "string_field: string" in ts_code
        assert "int_field: number" in ts_code
        assert "optional_field?: string" in ts_code
        assert "enum_field: FieldType" in ts_code

    def test_no_export(self, simple_wrapper: ModelWrapper) -> None:
        interface: ModelInterface = ModelInterface.from_model(simple_wrapper)
        interface.include_export = False
        ts_code: str = interface.to_js()

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
        self,
        parser: ControllerParser,
        field_name: str,
        field_type: Type[Any],
        expected_ts: str,
    ) -> None:
        class DynamicModel(BaseModel):
            pass

        setattr(DynamicModel, field_name, (field_type, ...))
        wrapper: ModelWrapper = parser._parse_model(DynamicModel)
        interface: ModelInterface = ModelInterface.from_model(wrapper)

        assert f"{field_name}: {expected_ts}" in interface.to_js()


class TestInheritanceHandling:
    def test_single_inheritance(self, child_wrapper: ModelWrapper) -> None:
        interface: ModelInterface = ModelInterface.from_model(child_wrapper)
        ts_code: str = interface.to_js()

        assert "interface ChildModel extends ParentModel" in ts_code
        assert "child_field: boolean" in ts_code
        assert "shared_field: number" in ts_code  # Should use child's type

    def test_multiple_inheritance(self, multi_inherit_wrapper: ModelWrapper) -> None:
        interface: ModelInterface = ModelInterface.from_model(multi_inherit_wrapper)
        ts_code: str = interface.to_js()

        assert "extends MultiInheritBase1, MultiInheritBase2" in ts_code
        assert "child_field: boolean" in ts_code

    def test_inheritance_chain(self, parser: ControllerParser) -> None:
        class A(BaseModel):
            a_field: str

        class B(A):
            b_field: str

        class C(B):
            c_field: str

        wrapper: ModelWrapper = parser._parse_model(C)
        interface: ModelInterface = ModelInterface.from_model(wrapper)

        assert "extends B" in interface.to_js()
        assert len(interface.include_superclasses) == 1
        assert interface.include_superclasses[0] == "B"


class TestComplexTypeHandling:
    def test_nested_model_interface(self, nested_wrapper: ModelWrapper) -> None:
        interface: ModelInterface = ModelInterface.from_model(nested_wrapper)
        ts_code: str = interface.to_js()

        assert "simple: SimpleModel" in ts_code
        assert "optional_simple?: SimpleModel" in ts_code
        assert "list_simple: Array<SimpleModel>" in ts_code
        assert "dict_simple: Record<string, SimpleModel>" in ts_code

    def test_generic_model(self, parser: ControllerParser) -> None:
        wrapper: ModelWrapper = parser._parse_model(GenericModel[str])
        interface: ModelInterface = ModelInterface.from_model(wrapper)
        ts_code: str = interface.to_js()

        assert "value: string" in ts_code
        assert "metadata: string" in ts_code

    def test_forward_reference(self, parser: ControllerParser) -> None:
        wrapper: ModelWrapper = parser._parse_model(CircularModel)
        interface: ModelInterface = ModelInterface.from_model(wrapper)
        ts_code: str = interface.to_js()

        assert "parent?: CircularModel" in ts_code


class TestEdgeCases:
    def test_empty_model(self, parser: ControllerParser) -> None:
        class EmptyModel(BaseModel):
            pass

        wrapper: ModelWrapper = parser._parse_model(EmptyModel)
        interface: ModelInterface = ModelInterface.from_model(wrapper)
        ts_code: str = interface.to_js()

        assert "interface EmptyModel {}" in ts_code

    def test_all_optional_fields(self, parser: ControllerParser) -> None:
        class OptionalModel(BaseModel):
            field1: Optional[str] = None
            field2: Optional[int] = None

        wrapper: ModelWrapper = parser._parse_model(OptionalModel)
        interface: ModelInterface = ModelInterface.from_model(wrapper)
        ts_code: str = interface.to_js()

        assert "field1?: string" in ts_code
        assert "field2?: number" in ts_code

    def test_union_types(self, parser: ControllerParser) -> None:
        class UnionModel(BaseModel):
            union_field: Union[str, int]
            optional_union: Optional[Union[bool, float]] = None

        wrapper: ModelWrapper = parser._parse_model(UnionModel)
        interface: ModelInterface = ModelInterface.from_model(wrapper)
        ts_code: str = interface.to_js()

        assert "union_field: string | number" in ts_code
        assert "optional_union?: boolean | number" in ts_code

    def test_literal_types(self, parser: ControllerParser) -> None:
        class LiteralModel(BaseModel):
            status: Literal["active", "inactive"]

        wrapper: ModelWrapper = parser._parse_model(LiteralModel)
        interface: ModelInterface = ModelInterface.from_model(wrapper)
        ts_code: str = interface.to_js()

        assert 'status: "active" | "inactive"' in ts_code

    def test_deep_generic_nesting(self, parser: ControllerParser) -> None:
        class DeepGeneric(BaseModel, Generic[T, S]):
            nested: GenericModel[List[T]]
            other: Dict[str, GenericModel[S]]

        wrapper: ModelWrapper = parser._parse_model(DeepGeneric[str, int])
        interface: ModelInterface = ModelInterface.from_model(wrapper)
        ts_code: str = interface.to_js()

        assert "nested: GenericModel" in ts_code
        assert "other: Record<string, GenericModel>" in ts_code


class TestAnnotationConversion:
    @pytest.mark.parametrize(
        "python_type,expected_ts",
        [
            (List[str], "Array<string>"),
            (Dict[str, int], "Record<string, number>"),
            (Optional[str], "string | undefined"),
            (Union[int, str, bool], "number | string | boolean"),
            (List[Dict[str, int]], "Array<Record<string, number>>"),
        ],
    )
    def test_annotation_conversion(
        self, parser: ControllerParser, python_type: Type[Any], expected_ts: str
    ) -> None:
        class AnnotationModel(BaseModel):
            field: python_type

        wrapper: ModelWrapper = parser._parse_model(AnnotationModel)
        interface: ModelInterface = ModelInterface.from_model(wrapper)
        ts_code: str = interface.to_js()

        # Remove spaces for consistent comparison
        ts_code_normalized: str = "".join(ts_code.split())
        expected_ts_normalized: str = "".join(expected_ts.split())

        assert expected_ts_normalized in ts_code_normalized
