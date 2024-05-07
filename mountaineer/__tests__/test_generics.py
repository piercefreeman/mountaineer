from typing import Generic, TypeVar

from mountaineer.generics import expand_typevars, get_typevar_mapping

T = TypeVar("T")
K = TypeVar("K")


class Base(Generic[T]):
    pass


class Intermediate(Base[T], Generic[T, K]):
    pass


class Final(Intermediate[int, str]):
    pass


def test_get_typevar_mapping():
    mapping = get_typevar_mapping(Final)

    assert mapping == {
        T: int,
        K: str,
    }


def test_expand_typevars():
    assert expand_typevars(
        {
            K: T,
            T: int,
        }
    ) == {
        K: int,
        T: int,
    }
