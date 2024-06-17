from pydantic import BaseModel

from mountaineer.__tests__.client_builder.conf_models import (
    MyEnum,
    MyIntEnum,
    MyModel,
    MyStrEnum,
)
from mountaineer.client_builder.build_schemas import (
    OpenAPISchema,
    OpenAPIToTypescriptSchemaConverter,
)
from mountaineer.client_builder.openapi import (
    gather_all_models,
)


class ChildNode(BaseModel):
    siblings: list["ChildNode"]


def test_gather_all_models_recursive():
    """
    Ensure that schemas can be specified recursively for nested elements.

    """
    converter = OpenAPIToTypescriptSchemaConverter()
    openapi_spec = OpenAPISchema(**converter.get_model_json_schema(ChildNode))

    found_models = gather_all_models(openapi_spec)
    assert len(found_models) == 1

    js_interfaces = converter.convert_schema_to_typescript(openapi_spec)
    assert js_interfaces == {
        "ChildNode": "interface ChildNode {\n  siblings: Array<ChildNode>;\n}"
    }


def test_model_gathering_pydantic_models():
    """
    Ensure we are able to traverse a single model definition for all the
    sub-models it uses.

    """
    schema = OpenAPISchema(**MyModel.model_json_schema())

    all_models = gather_all_models(schema)

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

    all_models = gather_all_models(schema)

    assert len(all_models) == 4
    assert {m.title for m in all_models} == {
        "EnumModel",
        "MyStrEnum",
        "MyIntEnum",
        "MyEnum",
    }
