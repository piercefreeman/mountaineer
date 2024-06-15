from enum import Enum, IntEnum

from pydantic import BaseModel, Field

from mountaineer.compat import StrEnum


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
