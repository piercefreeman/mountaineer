import pytest
from fastapi import Depends

from mountaineer.dependencies.base import DependenciesBase, get_function_dependencies


async def dep_1():
    return 1


async def dep_2(
    dep_1: int = Depends(dep_1),
):
    return 2 + dep_1


def dep_3(dep_2: int = Depends(dep_2)):
    return dep_2 + 3


class ExampleDependencies(DependenciesBase):
    dep_1 = dep_1
    dep_2 = dep_2
    dep_3 = dep_3


@pytest.mark.asyncio
async def test_get_function_dependencies_recursive():
    dep_fn = ExampleDependencies.dep_3

    async with get_function_dependencies(callable=dep_fn) as values:
        result = dep_fn(**values)
        assert result == 6


def test_incorrect_static_method():
    """
    Ensure static methods will throw an error on init

    """
    with pytest.raises(TypeError):

        class ExampleIncorrectDependency(DependenciesBase):
            @staticmethod
            async def dep_1():
                return 1
