from dataclasses import dataclass
from pydantic import BaseModel
from pydantic_core import PydanticUndefined
from filzl.annotation_helpers import yield_all_subtypes, make_optional_model


def test_yield_all_subtypes():
    class SubModel(BaseModel):
        sub_a: int

    class SubModelOnlyReferenced(BaseModel):
        sub_a: int

    @dataclass
    class SubDataclass1:
        sub_a: int
        sub_dataclass_forwardref: "SubDataclass2"

    @dataclass
    class SubDataclass2:
        sub_a: int

    class ComplexModel(BaseModel):
        a: str
        b: SubModel
        c: list[SubModel]
        d_forwardref: "SubModelOnlyReferenced"
        e_forwardref: list["SubModelOnlyReferenced"]
        f_dataclass: SubDataclass1

    # We need to pass along the global namespace so we're able to resolve the forward references
    # in the dataclasses. Pydantic does this for us at runtime.
    assert set(yield_all_subtypes(ComplexModel, _locals=locals())) == {
        # Regular models
        ComplexModel,
        SubModel,
        SubDataclass1,
        SubDataclass2,
        SubModelOnlyReferenced,
        # Regular types
        str,
        int,
        # Origins + Arguments
        list[SubModel],
        list[SubModelOnlyReferenced],
        # Origins
        list,
    }


def test_make_optional_model():
    class RequiredModel(BaseModel):
        required_item: str

    optional_model = make_optional_model(RequiredModel)

    # Ensure our original model is unchanged
    assert RequiredModel.model_fields["required_item"].default == PydanticUndefined

    # Our new model should have the same fields as the original
    # but with the required fields made optional
    assert list(optional_model.model_fields.keys()) == list(
        RequiredModel.model_fields.keys()
    )
    assert optional_model.model_fields["required_item"].default is None
