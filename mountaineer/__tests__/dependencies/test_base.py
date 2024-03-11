from inspect import signature

import pytest
from fastapi import Depends, Request
from typing_extensions import Callable

from mountaineer.dependencies.base import (
    DependenciesBase,
    get_function_dependencies,
    isolate_dependency_only_function,
)


@pytest.mark.asyncio
async def test_get_function_dependencies_recursive():
    async def dep_1():
        return 1

    async def dep_2(
        dep_1: int = Depends(dep_1),
    ):
        return 2 + dep_1

    def dep_3(dep_2: int = Depends(dep_2)):
        return dep_2 + 3

    with pytest.warns(DeprecationWarning):

        class ExampleDependencies(DependenciesBase):
            dep_1: Callable
            dep_2: Callable
            dep_3: Callable

    ExampleDependencies.dep_1 = dep_1
    ExampleDependencies.dep_2 = dep_2
    ExampleDependencies.dep_3 = dep_3

    async with get_function_dependencies(callable=ExampleDependencies.dep_3) as values:
        result = ExampleDependencies.dep_3(**values)
        assert result == 6


def test_incorrect_static_method():
    """
    Ensure static methods will throw an error on init

    """
    with pytest.warns(DeprecationWarning), pytest.raises(TypeError):

        class ExampleIncorrectDependency(DependenciesBase):
            @staticmethod
            async def dep_1():
                return 1


@pytest.mark.asyncio
async def test_dependency_overrides():
    def dep_1():
        return "Original Value"

    def dep_2(
        dep_1: str = Depends(dep_1),
    ):
        return f"Final Value: {dep_1}"

    def mocked_dep_1():
        return "Mocked Value"

    async with get_function_dependencies(
        callable=dep_2,
        dependency_overrides={
            dep_1: mocked_dep_1,
        },
    ) as values:
        result = dep_2(**values)
        assert result == "Final Value: Mocked Value"


class ExamplePayload:
    value: int


@pytest.mark.asyncio
async def test_isolate_dependency_only_function():
    def test_dependency():
        return 1

    def test_complex_function(
        payload: ExamplePayload,
        request: Request,
        resolved_dep: int = Depends(test_dependency),
    ):
        return resolved_dep

    modified_function = isolate_dependency_only_function(
        test_complex_function,
    )
    new_signature = signature(modified_function)
    assert set(new_signature.parameters.keys()) == {"resolved_dep"}

    # Now try to execute the dependencies
    async with get_function_dependencies(
        callable=modified_function,
    ) as values:
        assert values == {"resolved_dep": 1}
