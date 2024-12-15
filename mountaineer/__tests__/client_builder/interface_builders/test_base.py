from datetime import date, datetime, time
from enum import Enum
from typing import (
    Any,
    Dict,
    List,
    Literal,
    Optional,
    Set,
    Tuple,
    Type,
    TypeVar,
    Union,
    cast,
)
from uuid import UUID

import pytest
from fastapi import UploadFile
from pydantic import BaseModel

from mountaineer.client_builder.interface_builders.base import InterfaceBase
from mountaineer.client_builder.parser import (
    EnumWrapper,
    ModelWrapper,
    SelfReference,
    WrapperName,
)
from mountaineer.client_builder.types import (
    DictOf,
    ListOf,
    LiteralOf,
    Or,
    SetOf,
    TupleOf,
    TypeDefinition,
)


# Test Models and Types
class Status(Enum):
    ACTIVE = "active"
    INACTIVE = "inactive"
    PENDING = "pending"


class SimpleModel(BaseModel):
    name: str
    count: int
    active: bool


class NestedModel(BaseModel):
    status: Status
    data: SimpleModel
    optional: Optional[SimpleModel]


class ComplexTypes(BaseModel):
    list_field: List[str]
    dict_field: Dict[str, int]
    set_field: Set[float]
    tuple_field: Tuple[str, int]
    union_field: Union[str, int]
    literal_field: Literal["a", "b", "c"]


# Test Implementation
T = TypeVar("T")


class TypeConverter(InterfaceBase):
    """Helper class for testing the abstract base model"""

    @classmethod
    def convert(cls, value: Any) -> str:
        return cast(str, cls._get_annotated_value(value))


# Test Fixtures
@pytest.fixture
def model_wrapper() -> ModelWrapper:
    return ModelWrapper(
        name=WrapperName("SimpleModel"),
        module_name="test_module",
        model=SimpleModel,
        isolated_model=SimpleModel,
        superclasses=[],
        value_models=[],
    )


@pytest.fixture
def enum_wrapper() -> EnumWrapper:
    return EnumWrapper(
        name=WrapperName("Status"),
        module_name="test_module",
        enum=Status,
    )


@pytest.fixture
def self_reference() -> SelfReference:
    return SelfReference(
        name="CircularModel",
        model=SimpleModel,
    )


class TestPrimitiveTypeMapping:
    @pytest.mark.parametrize(
        "py_type,ts_type",
        [
            (str, "string"),
            (int, "number"),
            (float, "number"),
            (bool, "boolean"),
            (datetime, "string"),
            (date, "string"),
            (time, "string"),
            (UUID, "string"),
            (UploadFile, "Blob"),
            (None, "null"),
            (Any, "any"),
        ],
    )
    def test_primitive_type_mapping(self, py_type: Type[Any], ts_type: str) -> None:
        result: str = TypeConverter.convert(py_type)
        assert result == ts_type

    def test_none_type_variations(self) -> None:
        assert TypeConverter.convert(None) == "null"
        assert TypeConverter.convert(type(None)) == "null"

    def test_any_type_fallback(self) -> None:
        class CustomType:
            pass

        result: str = TypeConverter.convert(CustomType)
        assert result == "any"


class TestComplexTypeHandling:
    def test_list_conversion(self) -> None:
        type_def: ListOf = ListOf(str)
        result: str = TypeConverter.convert(type_def)
        assert result == "Array<string>"

    def test_nested_list_conversion(self) -> None:
        type_def: ListOf = ListOf(ListOf(str))
        result: str = TypeConverter.convert(type_def)
        assert result == "Array<Array<string>>"

    def test_dict_conversion(self) -> None:
        type_def: DictOf = DictOf(str, int)
        result: str = TypeConverter.convert(type_def)
        assert result == "Record<string, number>"

    def test_set_conversion(self) -> None:
        type_def: SetOf = SetOf(float)
        result: str = TypeConverter.convert(type_def)
        assert result == "Set<number>"

    def test_tuple_conversion(self) -> None:
        type_def = TupleOf(str, int, bool)
        result: str = TypeConverter.convert(type_def)
        assert result == "[string,number,boolean]"

    def test_union_conversion(self) -> None:
        type_def = Or(str, int, bool)
        result: str = TypeConverter.convert(type_def)
        assert result == "string | number | boolean"

    def test_literal_conversion(self) -> None:
        type_def = LiteralOf("active", "inactive")
        result: str = TypeConverter.convert(type_def)
        assert result == '"active" | "inactive"'

    @pytest.mark.parametrize(
        "type_def,expected",
        [
            (DictOf(str, ListOf(int)), "Record<string, Array<number>>"),
            (ListOf(DictOf(str, bool)), "Array<Record<string, boolean>>"),
            (
                Or(ListOf(str), DictOf(str, int)),
                "Array<string> | Record<string, number>",
            ),
        ],
    )
    def test_nested_complex_types(
        self, type_def: TypeDefinition, expected: str
    ) -> None:
        result: str = TypeConverter.convert(type_def)
        assert result == expected


class TestModelHandling:
    def test_model_wrapper_conversion(self, model_wrapper: ModelWrapper) -> None:
        result: str = TypeConverter.convert(model_wrapper)
        assert result == "SimpleModel"

    def test_enum_wrapper_conversion(self, enum_wrapper: EnumWrapper) -> None:
        result: str = TypeConverter.convert(enum_wrapper)
        assert result == "Status"

    def test_self_reference_conversion(self, self_reference: SelfReference) -> None:
        result: str = TypeConverter.convert(self_reference)
        assert result == "CircularModel"

    def test_nested_model_references(self, model_wrapper: ModelWrapper) -> None:
        type_def: ListOf = ListOf(model_wrapper)
        result: str = TypeConverter.convert(type_def)
        assert result == "Array<SimpleModel>"


class TestComplexScenarios:
    def test_deeply_nested_structure(self) -> None:
        # Create a deeply nested structure
        deep_type = ListOf(
            DictOf(str, Or(ListOf(TupleOf(str, int)), DictOf(str, SetOf(float))))
        )
        result = TypeConverter.convert(deep_type)
        expected = "Array<Record<string, Array<[string,number]> | Record<string, Set<number>>>>"
        assert result == expected

    def test_mixed_model_and_primitive_types(
        self, model_wrapper: ModelWrapper, enum_wrapper: EnumWrapper
    ) -> None:
        type_def = Or(model_wrapper, ListOf(enum_wrapper), DictOf(str, int))
        result: str = TypeConverter.convert(type_def)
        assert "SimpleModel | Array<Status> | Record<string, number>" == result

    def test_complex_union_types(self) -> None:
        # Test union with various nested types
        type_def = Or(
            ListOf(str),
            DictOf(str, bool),
            SetOf(int),
            TupleOf(str, int),
            LiteralOf("a", "b"),
        )
        result: str = TypeConverter.convert(type_def)
        expected: str = 'Array<string> | Record<string, boolean> | Set<number> | [string,number] | "a" | "b"'
        assert result == expected

    @pytest.mark.parametrize(
        "type_def,expected",
        [
            (
                DictOf(LiteralOf("id", "name"), Or(str, int)),
                'Record<"id" | "name", string | number>',
            ),
            (
                ListOf(TupleOf(LiteralOf("GET", "POST"), str)),
                'Array<["GET" | "POST",string]>',
            ),
            (
                SetOf(Or(LiteralOf(1, 2), LiteralOf("a", "b"))),
                'Set<1 | 2 | "a" | "b">',
            ),
        ],
    )
    def test_complex_literal_combinations(
        self, type_def: TypeDefinition, expected: str
    ) -> None:
        result: str = TypeConverter.convert(type_def)
        assert result == expected
