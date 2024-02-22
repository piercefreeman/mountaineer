import pytest
from fastapi import Depends
from pydantic import BaseModel

from filzl_daemons.actions import action


class ExampleModel(BaseModel):
    pass


def test_requires_async():
    with pytest.raises(
        ValueError, match="Function test_sync_action is not a coroutine function"
    ):

        @action
        def test_sync_action():
            pass


def test_requires_zero_or_one_argument():
    @action
    async def test_one_argument(payload: ExampleModel) -> None:
        pass

    @action
    async def test_no_argument() -> None:
        pass

    with pytest.raises(TypeError, match="must have no arguments or the first argument"):

        @action
        async def test_two_arguments(
            payload: ExampleModel, other: ExampleModel
        ) -> None:
            pass


def test_allows_dependencies():
    def example_dependency():
        yield "example_dependency"

    @action
    async def test_dependencies(
        payload: BaseModel,
        user_model: str = Depends(example_dependency),
    ) -> None:
        pass
