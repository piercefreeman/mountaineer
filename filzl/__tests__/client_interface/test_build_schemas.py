from filzl.client_interface.build_schemas import (
    OpenAPIToTypeScriptConverter,
    OpenAPISchema,
)
from pydantic import BaseModel, Field, create_model
import pytest


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
    converter = OpenAPIToTypeScriptConverter()
    result = converter.convert(MyModel)
    assert "interface MyModel {" in result


def test_model_gathering():
    schema = OpenAPISchema(**MyModel.model_json_schema())

    converter = OpenAPIToTypeScriptConverter()
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

    converter = OpenAPIToTypeScriptConverter()
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

    converter = OpenAPIToTypeScriptConverter()
    converter.validate_typescript_candidate(ValidDictModel)

    with pytest.raises(ValueError):
        converter.validate_typescript_candidate(InvalidDictModel)
