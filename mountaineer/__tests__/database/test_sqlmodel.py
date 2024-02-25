from typing import Generic, TypeVar
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from mountaineer.database.sqlmodel import Field, SQLModel

T = TypeVar("T")


def test_generic_data_models():
    class GenericModel(SQLModel, Generic[T]):
        id: UUID = Field(default_factory=uuid4, primary_key=True)
        value: T
        default_value: str = "default"

    class MySubclass(GenericModel[int], table=True):
        pass

    obj = MySubclass(value=1)
    assert obj.value == 1

    with pytest.raises(ValidationError):
        obj = MySubclass(value="abc")  # type: ignore
