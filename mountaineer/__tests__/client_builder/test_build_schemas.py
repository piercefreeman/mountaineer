from enum import Enum, IntEnum
from json import dumps as json_dumps
from typing import Any, Generic, Literal, TypeVar

import pytest
from pydantic import BaseModel, Field, create_model

from mountaineer.client_builder.build_schemas import (
    OpenAPISchema,
    OpenAPIToTypescriptSchemaConverter,
)
from mountaineer.client_builder.openapi import OpenAPIProperty, OpenAPISchemaType
from mountaineer.compat import StrEnum
from mountaineer.logging import LOGGER

T = TypeVar("T")


class SubModel1(BaseModel):
    sub_a: str


class SubModel2(BaseModel):
    sub_b: int


class MyStrEnum(StrEnum):
    VALUE_1 = "value_1"
    VALUE_2 = "value_2"


class MyIntEnum(IntEnum):
    VALUE_1 = 1
    VALUE_2 = 2


class MyEnum(Enum):
    VALUE_1 = "value_1"
    VALUE_2 = 5


class MyModel(BaseModel):
    a: str = Field(description="The a field")
    b: int
    c: SubModel1
    d: list[SubModel1]
    both_sub: list[SubModel1 | SubModel2 | None]
    sub_map: dict[str, SubModel1 | None]


def test_basic_interface():
    converter = OpenAPIToTypescriptSchemaConverter()

    json_schema = OpenAPISchema(**converter.get_model_json_schema(MyModel))
    result = converter.convert_schema_to_typescript(json_schema)

    assert set(result.keys()) == {"MyModel", "SubModel1", "SubModel2", "Sub Map"}
    assert "interface MyModel {" in result["MyModel"]


def test_model_gathering_pydantic_models():
    """
    Ensure we are able to traverse a single model definition for all the
    sub-models it uses.

    """
    schema = OpenAPISchema(**MyModel.model_json_schema())

    converter = OpenAPIToTypescriptSchemaConverter()
    all_models = converter.gather_all_models(schema)

    # OpenAPI makes an object for the dictionary as well
    assert len(all_models) == 4
    assert {m.title for m in all_models} == {
        "SubModel1",
        "SubModel2",
        "MyModel",
        "Sub Map",
    }


def test_model_gathering_enum_models():
    class EnumModel(BaseModel):
        a: MyStrEnum
        b: MyIntEnum
        c: MyEnum

    schema = OpenAPISchema(**EnumModel.model_json_schema())

    converter = OpenAPIToTypescriptSchemaConverter()
    all_models = converter.gather_all_models(schema)

    assert len(all_models) == 4
    assert {m.title for m in all_models} == {
        "EnumModel",
        "MyStrEnum",
        "MyIntEnum",
        "MyEnum",
    }


@pytest.mark.parametrize(
    "python_type,expected_typescript_types",
    [
        (str, ["value: string"]),
        (int, ["value: number"]),
        (SubModel1, ["value: SubModel1"]),
        (list[SubModel1], ["value: Array<SubModel1>"]),
        (dict[str, SubModel1], ["value: Record<string, SubModel1>"]),
        (dict[str, int], ["value: Record<string, number>"]),
        (dict[str, dict[str, str]], ["value: Record<string, Record<string, string>>"]),
        ("SubModel1", ["value: SubModel1"]),
        (MyStrEnum, ["value: MyStrEnum"]),
        (MyIntEnum, ["value: MyIntEnum"]),
        (MyEnum, ["value: MyEnum"]),
        (str | None, ["value: null | string"]),
        (list[str] | None, ["value: Array<string> | null"]),
        (list[str | int] | None, ["value: Array<number | string> | null"]),
        (list | None, ["value: Array<any> | null"]),
        (
            dict[str, str | None | int | float],
            ["value: Record<string, null | number | string>"],
        ),
        (list[str | None] | None, ["value: Array<null | string> | null"]),
        (tuple[str, str], ["value: [string, string]"]),
        (tuple[str, int | None], ["value: [string, null | number]"]),
        (list[tuple[str, int] | str], ["value: Array<[string, number] | string>"]),
        (Literal["my_value"], ["value: 'my_value'"]),
        (Literal["my_value"] | Literal[True], ["value: 'my_value' | true"]),  # type: ignore
        (bool, ["value: boolean"]),
        (float, ["value: number"]),
        (Any, ["value: any"]),
        # We don't consider types that would encompass other types, so right now
        # we just parse separately
        (Any | None, ["value: any | null"]),  # type: ignore
        # OpenAPI doesn't support bytes, so it casts them as strings
        (bytes, ["value: string"]),
        # OpenAPI doesn't support sets, so it casts them as arrays
        (set[str], ["value: Array<string>"]),
    ],
)
def test_python_to_typescript_types(
    python_type: type, expected_typescript_types: list[str]
):
    """
    Test type resolution when attached to a given model's field
    """
    # Create a model schema automatically with the passed in typing
    fake_model = create_model(
        "FakeModel",
        value=(python_type, Field()),
    )

    LOGGER.debug(f"Raw schema: {fake_model.model_json_schema()}")
    schema = OpenAPISchema(**fake_model.model_json_schema())

    converter = OpenAPIToTypescriptSchemaConverter()
    interface_definition = converter.convert_schema_to_interface(
        schema,
        base=schema,
        defaults_are_required=False,
        all_fields_required=False,
    )

    for expected_str in expected_typescript_types:
        assert expected_str in interface_definition


def test_require_json_dictionaries():
    """
    JSON dictionaries can only serialize with string keys, so we need to make sure
    that the TypeScript interface enforces this.
    """

    class InvalidDictModel(BaseModel):
        value: dict[int, str]

    class ValidDictModel(BaseModel):
        value: dict[str, str]

    converter = OpenAPIToTypescriptSchemaConverter()
    converter.validate_typescript_candidate(ValidDictModel)

    with pytest.raises(ValueError):
        converter.validate_typescript_candidate(InvalidDictModel)


def test_get_model_json_schema_excludes_masked_fields():
    """
    Ensure we avoid serializing "excluded" fields.
    """

    class ExcludedModel(BaseModel):
        a: str

    class IncludedModel(BaseModel):
        b: str

    class MainModel(BaseModel):
        excluded_obj: ExcludedModel | None = Field(default=None, exclude=True)
        included_obj: IncludedModel | None

    builder = OpenAPIToTypescriptSchemaConverter()
    raw_openapi_result = json_dumps(MainModel.model_json_schema())
    fixed_openapi_result = json_dumps(builder.get_model_json_schema(MainModel))

    # First we check that pydantic actually does serialize excluded fields
    # If this starts failing, we should be able to remove our workaround
    assert "excluded_obj" in raw_openapi_result
    assert "ExcludedModel" in raw_openapi_result

    assert "excluded_obj" not in fixed_openapi_result
    assert "ExcludedModel" not in fixed_openapi_result
    assert "included_obj" in fixed_openapi_result
    assert "IncludedModel" in fixed_openapi_result


def test_format_enums():
    class MyModel(BaseModel):
        # String type enums
        a: MyStrEnum
        # Int type enums
        b: MyIntEnum
        # Mixed type enums: string and int
        c: MyEnum

    converter = OpenAPIToTypescriptSchemaConverter()
    json_schema = OpenAPISchema(**converter.get_model_json_schema(MyModel))
    js_interfaces = converter.convert_schema_to_typescript(json_schema)

    assert (
        js_interfaces["MyStrEnum"]
        == "enum MyStrEnum {\nValue1 = 'value_1',\nValue2 = 'value_2'\n}"
    )
    assert (
        js_interfaces["MyIntEnum"] == "enum MyIntEnum {\nValue__1 = 1,\nValue__2 = 2\n}"
    )
    assert (
        js_interfaces["MyEnum"] == "enum MyEnum {\nValue1 = 'value_1',\nValue__5 = 5\n}"
    )


def test_format_generics():
    class MyModel(BaseModel, Generic[T]):
        a: T

    converter = OpenAPIToTypescriptSchemaConverter()
    json_schema = OpenAPISchema(**converter.get_model_json_schema(MyModel[str]))
    js_interfaces = converter.convert_schema_to_typescript(json_schema)

    assert js_interfaces == {"MyModel[str]": "interface MyModelStr {\n  a: string;\n}"}


@pytest.mark.parametrize("defaults_are_required", [True, False])
def test_defaults_are_required(defaults_are_required: bool):
    class MyModelExplicitField(BaseModel):
        a: str = Field(default="default value")

    class MyModelImplicitField(BaseModel):
        a: str = "default value"

    # Both behaviors should be the same
    for base_model in [MyModelExplicitField, MyModelImplicitField]:
        converter = OpenAPIToTypescriptSchemaConverter()

        json_schema = OpenAPISchema(**converter.get_model_json_schema(base_model))
        js_interfaces = converter.convert_schema_to_typescript(
            json_schema, defaults_are_required=defaults_are_required
        )
        model_name = base_model.__name__

        if defaults_are_required:
            assert "a: string" in js_interfaces[model_name]
            assert "a?: string" not in js_interfaces[model_name]
        else:
            assert "a: string" not in js_interfaces[model_name]
            assert "a?: string" in js_interfaces[model_name]


@pytest.mark.parametrize(
    "model_title, expected_interface",
    [
        ("MyModel", "MyModel"),
        # We've seen cases where sub-variables are converted to multiple words
        ("My Model", "MyModel"),
        ("My model", "MyModel"),
    ],
)
def test_get_typescript_interface_name(model_title: str, expected_interface: str):
    converter = OpenAPIToTypescriptSchemaConverter()
    assert (
        converter.get_typescript_interface_name(
            OpenAPIProperty.from_meta(
                title=model_title,
                variable_type=OpenAPISchemaType.OBJECT,
            )
        )
        == expected_interface
    )


class ChildNode(BaseModel):
    siblings: list["ChildNode"]


def test_gather_all_models_recursive():
    """
    Ensure that schemas can be specified recursively for nested elements.

    """
    converter = OpenAPIToTypescriptSchemaConverter()
    openapi_spec = OpenAPISchema(**converter.get_model_json_schema(ChildNode))

    found_models = converter.gather_all_models(openapi_spec)
    assert len(found_models) == 1

    js_interfaces = converter.convert_schema_to_typescript(openapi_spec)
    assert js_interfaces == {
        "ChildNode": "interface ChildNode {\n  siblings: Array<ChildNode>;\n}"
    }
