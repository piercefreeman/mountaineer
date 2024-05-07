from enum import Enum
from typing import Any, Type, Union

import pytest
from sqlmodel import SQLModel

from mountaineer.migrations.generics import (
    is_type_compatible,
    remove_null_type,
)


class SomeEnum(Enum):
    A = "A"


class SomeSuperClass:
    pass


class SomeSubClass(SomeSuperClass):
    pass


class SomeTable(SQLModel):
    a: int


@pytest.mark.parametrize(
    "obj_type, target_type, expected",
    [
        # Basic types
        (int, int, True),
        (str, str, True),
        (int, str, False),
        (int, float, False),
        # Subclasses
        (bool, int, True),
        (int, object, True),
        (SomeSubClass, SomeSuperClass, True),
        # Instance can match classes
        (SomeSubClass(), SomeSuperClass, True),
        ([SomeSubClass], list[SomeSuperClass], True),
        # Enums
        (SomeEnum, Type[Enum], True),
        # Unions with new syntax
        (int, Union[int, str], True),
        (str, Union[int, str], True),
        (float, Union[int, str], False),
        # Unions with old syntax using type hints
        (int, Union[int, str], True),
        (str, Union[int, str], True),
        (float, Union[int, str], False),
        # Complex types involving collections
        (list[int], list[int], True),
        (list[int], list[str], False),
        (dict[str, int], dict[str, int], True),
        (dict[str, int], dict[str, str], False),
        # More complex union cases
        (list[int], Union[list[int], dict[str, str]], True),
        (dict[str, str], Union[list[int], dict[str, str]], True),
        (dict[str, float], Union[list[int], dict[str, str]], False),
        # Pipe operator if Python >= 3.10
        (int, int | str, True),
        (int | str, int | str | float, True),
        (str, int | str, True),
        (float, int | str, False),
        # Nested unions
        (int, list[int | float | str] | int | float | str, True),
        # Optional types
        (None, int | str | None, True),
        (int, int | str | None, True),
        # Value evaluation for sequences
        ([1, 2, 3], list[int], True),
        ([1, 2, "3"], list[int], False),
    ],
)
def test_is_type_compatible(obj_type: Any, target_type: Any, expected: bool):
    raw_result = is_type_compatible(obj_type, target_type)
    bool_result = raw_result != float("inf")
    assert bool_result == expected


@pytest.mark.parametrize(
    "typehint, expected",
    [
        (int, int),
        (str, str),
        (int | None, int),
        (str | None, str),
        (Union[int, None], int),
    ],
)
def test_remove_null_type(typehint: Any, expected: bool):
    assert remove_null_type(typehint) == expected
