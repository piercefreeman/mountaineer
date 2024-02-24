from pathlib import Path

import pytest
from pydantic.main import BaseModel

from mountaineer.actions.fields import FunctionActionType, get_function_metadata
from mountaineer.actions.passthrough import passthrough
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
        @passthrough(response_model=ExamplePassthroughModel)
        def get_external_data(self):
            return dict(
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
        def call_passthrough(self, payload: dict):
            self.counter += 1
            return dict(status="success")

        @passthrough
        async def call_passthrough_async(self, payload: dict):
            self.counter += 1
            return dict(status="success")

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
        "passthrough": {
            "status": "success",
        }
    }

    assert return_value_sync == expected_response
    assert return_value_async == expected_response

    assert controller.counter == 2

    # Our passthrough logic by definition should not re-render
    assert controller.render_counts == 0
