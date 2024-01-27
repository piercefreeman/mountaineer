from filzl.interface_gen import OpenAPIToTypeScriptConverter, OpenAPISchema
from pydantic import BaseModel, Field

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

def test_basic_interface():

    converter = OpenAPIToTypeScriptConverter()
    result = converter.convert(MyModel.model_json_schema())
    print(result)

    raise ValueError

def test_model_gathering():
    schema = OpenAPISchema(**MyModel.model_json_schema())

    converter = OpenAPIToTypeScriptConverter()
    all_models = converter.gather_all_models(schema)

    assert len(all_models) == 3
    assert {m.title for m in all_models} == {"SubModel1", "SubModel2", "MyModel"}


def test_exhaustive_python_types():
    # Create a model schema automatically with the passed in typing
    pass
