from dataclasses import dataclass

from pydantic import BaseModel

from mountaineer.annotation_helpers import yield_all_subtypes


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
