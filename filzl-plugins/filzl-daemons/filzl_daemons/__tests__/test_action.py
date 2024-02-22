from typing import cast

import pytest
from fastapi import Depends
from pydantic import BaseModel

from filzl_daemons.actions import ActionExecutionStub, action, call_action


class ExampleModel(BaseModel):
    value: str | None = None


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


@pytest.mark.asyncio
async def test_allows_dependencies():
    def example_dependency():
        yield "example_dependency"

    @action
    async def test_dependencies(
        payload: ExampleModel,
        resolved_dependency: str = Depends(example_dependency),
    ) -> ExampleModel:
        return ExampleModel(value=resolved_dependency)

    action_result = cast(
        ActionExecutionStub,
        await test_dependencies(ExampleModel()),
    )
    result = await call_action(action_result.registry_id, action_result.input_body)
    assert result.value == "example_dependency"
