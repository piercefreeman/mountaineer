from json import dumps as json_dumps
from typing import Any, Generic, Literal, TypeVar

import pytest
from pydantic import BaseModel, Field, create_model

from mountaineer.__tests__.client_builder.conf_models import (
    MyEnum,
    MyIntEnum,
    MyModel,
    MyStrEnum,
    SubModel1,
)
from mountaineer.client_builder.build_schemas import (
    OpenAPISchema,
    OpenAPIToTypescriptSchemaConverter,
)
from mountaineer.client_builder.openapi import (
    OpenAPIProperty,
    OpenAPISchemaType,
)
from mountaineer.logging import LOGGER

T = TypeVar("T")


def test_basic_interface():
    converter = OpenAPIToTypescriptSchemaConverter()

    json_schema = OpenAPISchema(**converter.get_model_json_schema(MyModel))
    result = converter.convert_schema_to_typescript(json_schema)

    assert set(result.keys()) == {"MyModel", "SubModel1", "SubModel2", "Sub Map"}
    assert "interface MyModel {" in result["MyModel"]


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
        (bytes, ["value: Blob"]),
        # We don't consider types that would encompass other types, so right now
        # we just parse separately
        (Any | None, ["value: any | null"]),  # type: ignore
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


def test_nested_all_fields_required():
    class ThirdNestedModel(BaseModel):
        c: str

    class MyModelNestedModel(BaseModel):
        b: list[ThirdNestedModel] = []

    class MyModelMainModel(BaseModel):
        a: list[MyModelNestedModel]

    # Both behaviors should be the same
    converter = OpenAPIToTypescriptSchemaConverter()

    json_schema = OpenAPISchema(**converter.get_model_json_schema(MyModelMainModel))
    js_interfaces = converter.convert_schema_to_typescript(
        json_schema, all_fields_required=True
    )

    assert "a: Array<MyModelNestedModel>" in js_interfaces["MyModelMainModel"]
    assert "a?: Array<MyModelNestedModel>" not in js_interfaces["MyModelMainModel"]

    assert "b: Array<ThirdNestedModel>" in js_interfaces["MyModelNestedModel"]
    assert "b?: Array<ThirdNestedModel>" not in js_interfaces["MyModelNestedModel"]


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
