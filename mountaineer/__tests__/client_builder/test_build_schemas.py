from json import dumps as json_dumps

import pytest
from pydantic import BaseModel, Field, create_model

from mountaineer.client_builder.build_schemas import (
    OpenAPISchema,
    OpenAPIToTypescriptSchemaConverter,
)


class SubModel1(BaseModel):
    sub_a: str


class SubModel2(BaseModel):
    sub_b: int


class MyModel(BaseModel):
    a: str = Field(description="The a field")
    b: int
    c: SubModel1
    d: list[SubModel1]
    both_sub: list[SubModel1 | SubModel2 | None]
    sub_map: dict[str, SubModel1 | None]


def test_basic_interface():
    converter = OpenAPIToTypescriptSchemaConverter()
    result = converter.convert(MyModel)
    assert set(result.keys()) == {"MyModel", "SubModel1", "SubModel2", "Sub Map"}
    assert "interface MyModel {" in result["MyModel"]


def test_model_gathering():
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


@pytest.mark.parametrize(
    "python_type,expected_typescript_types",
    [
        (str, ["value: string"]),
        (int, ["value: number"]),
        (SubModel1, ["value: SubModel1"]),
        (list[SubModel1], ["value: Array<SubModel1>"]),
        (dict[str, SubModel1], ["value: Record<string, SubModel1>"]),
        (dict[str, int], ["value: Record<string, number>"]),
        ("SubModel1", ["value: SubModel1"]),
    ],
)
def test_python_to_typescript_types(
    python_type: type, expected_typescript_types: list[str]
):
    # Create a model schema automatically with the passed in typing
    fake_model = create_model(
        "FakeModel",
        value=(python_type, Field()),
    )

    schema = OpenAPISchema(**fake_model.model_json_schema())

    converter = OpenAPIToTypescriptSchemaConverter()
    interface_definition = converter.convert_schema_to_interface(schema, base=schema)

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
