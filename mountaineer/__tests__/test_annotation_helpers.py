import sys
from dataclasses import dataclass

from pydantic import BaseModel

from mountaineer.annotation_helpers import yield_all_subtypes

if sys.version_info >= (3, 11):
    from enum import StrEnum
else:
    from backports.strenum import StrEnum


def test_yield_all_subtypes():
    class MyStrEnum(StrEnum):
        enum_a = "enum_a"
        enum_b = "enum_b"

    class SubModel1(BaseModel):
        sub_a: int

    class SubModel2(BaseModel):
        sub_a: MyStrEnum

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
        b: SubModel1
        c: list[SubModel1]
        d_forwardref: "SubModelOnlyReferenced"
        e_forwardref: list["SubModelOnlyReferenced"]
        f_dataclass: SubDataclass1
        g: list[SubModel2]

    # We need to pass along the global namespace so we're able to resolve the forward references
    # in the dataclasses. Pydantic does this for us at runtime.
    assert set(yield_all_subtypes(ComplexModel, _locals=locals())) == {
        # Regular models
        ComplexModel,
        SubModel1,
        SubModel2,
        SubDataclass1,
        SubDataclass2,
        SubModelOnlyReferenced,
        # Regular types
        str,
        int,
        # Origins + Arguments
        list[SubModel1],
        list[SubModel2],
        list[SubModelOnlyReferenced],
        # Origins
        list,
        MyStrEnum,
    }
