from pathlib import Path
from typing import Any, AsyncIterator, Iterator, cast

import pytest
from fastapi.responses import StreamingResponse
from fastapi.testclient import TestClient
from pydantic import BaseModel

from mountaineer.actions.fields import FunctionActionType, get_function_metadata
from mountaineer.actions.passthrough import (
    passthrough,
)
from mountaineer.annotation_helpers import MountaineerUnsetValue
from mountaineer.app import AppController
from mountaineer.controller import ControllerBase
from mountaineer.render import RenderBase


def test_markup_passthrough():
    """
    Check that the @passthrough decorator extracts the expected
    data from our model definition.
    """

    class ExamplePassthroughModel(BaseModel):
        first_name: str

    class TestController(ControllerBase):
        @passthrough
        def get_external_data(self) -> ExamplePassthroughModel:
            return ExamplePassthroughModel(
                first_name="John",
            )

    metadata = get_function_metadata(TestController.get_external_data)
    assert metadata.action_type == FunctionActionType.PASSTHROUGH
    assert metadata.get_passthrough_model() == ExamplePassthroughModel
    assert metadata.function_name == "get_external_data"
    assert isinstance(metadata.reload_states, MountaineerUnsetValue)
    assert isinstance(metadata.render_model, MountaineerUnsetValue)
    assert isinstance(metadata.url, MountaineerUnsetValue)
    assert isinstance(metadata.return_model, MountaineerUnsetValue)
    assert isinstance(metadata.render_router, MountaineerUnsetValue)


class ExampleRenderModel(RenderBase):
    value_a: str
    value_b: str


class ExamplePassthroughModel(BaseModel):
    status: str


@pytest.mark.asyncio
async def test_can_call_passthrough():
    class TestController(ControllerBase):
        url: str = "/test/{query_id}/"

        def __init__(self):
            super().__init__()
            self.counter = 0
            self.render_counts = 0

        def render(
            self,
            query_id: int,
        ) -> ExampleRenderModel:
            self.render_counts += 1
            return ExampleRenderModel(
                value_a="Hello",
                value_b="World",
            )

        @passthrough
        def call_passthrough(self, payload: dict) -> ExamplePassthroughModel:
            self.counter += 1
            return ExamplePassthroughModel(status="success")

        @passthrough
        async def call_passthrough_async(
            self, payload: dict
        ) -> ExamplePassthroughModel:
            self.counter += 1
            return ExamplePassthroughModel(status="success")

    app = AppController(view_root=Path())
    controller = TestController()
    app.register(controller)

    return_value_sync = await controller.call_passthrough(
        {},
    )

    return_value_async = await controller.call_passthrough_async(
        {},
    )

    # The response payload should be the same both both sync and async endpoints
    expected_response = {
        "passthrough": ExamplePassthroughModel(
            status="success",
        )
    }

    assert return_value_sync == expected_response
    assert return_value_async == expected_response

    assert controller.counter == 2

    # Our passthrough logic by definition should not re-render
    assert controller.render_counts == 0


class ExampleModel(BaseModel):
    value: str


class ExampleIterableController(ControllerBase):
    url = "/example"

    async def render(self) -> None:
        pass

    @passthrough
    async def get_data(self) -> AsyncIterator[ExampleModel]:
        yield ExampleModel(value="Hello")
        yield ExampleModel(value="World")


def test_extracts_iterable():
    controller = ExampleIterableController()
    metadata = get_function_metadata(controller.get_data)
    assert metadata.passthrough_model == ExampleModel
    # Explicitly validate type here instead of using global constant
    assert metadata.media_type == "text/event-stream"


def test_disallows_invalid_iterables():
    # Sync functions
    with pytest.raises(ValueError, match="async generators are supported"):

        class ExampleController1(ControllerBase):
            @passthrough
            def sync_iterable(self) -> Iterator[ExampleModel]:
                yield ExampleModel(value="Hello")
                yield ExampleModel(value="World")

    # Generator without marking up the response model
    with pytest.raises(ValueError, match="must have a response_model"):

        class ExampleController2(ControllerBase):
            @passthrough
            async def no_response_type_iterable(self) -> None:  # type: ignore
                yield ExampleModel(value="Hello")  # type: ignore
                yield ExampleModel(value="World")  # type: ignore


@pytest.mark.asyncio
async def test_can_call_iterable():
    app = AppController(view_root=Path())
    controller = ExampleIterableController()
    app.register(controller)

    # Ensure we return a valid StreamingResponse when called directly from the code
    return_value_sync = cast(Any, await controller.get_data())
    assert isinstance(return_value_sync, StreamingResponse)

    # StreamingResponses are intended to be read by an ASGI server, so we'll use the TestClient to simulate one instead of calling directly
    passthrough_url = get_function_metadata(controller.get_data).get_url()

    client = TestClient(app.app)
    lines: list[str] = []
    with client.stream(
        "POST",
        passthrough_url,
        json={},
    ) as response:
        for line in response.iter_lines():
            lines.append(line)

    assert lines == [
        'data: {"passthrough": {"value": "Hello"}}',
        'data: {"passthrough": {"value": "World"}}',
    ]
