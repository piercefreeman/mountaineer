from pydantic.main import BaseModel

from filzl.actions.fields import FunctionActionType, get_function_metadata
from filzl.actions.sideeffect import sideeffect
from filzl.controller import ControllerBase
from filzl.render import RenderBase


def test_markup_sideeffect():
    """
    Check that the @sideeffect decorator extracts the expected
    data from our model definition.
    """

    class ExampleRenderModel(RenderBase):
        value_a: str
        value_b: str

    class ExamplePassthroughModel(BaseModel):
        first_name: str

    class TestController(ControllerBase):
        # We declare as complicated a payload as @sideeffect supports so we can
        # see the full amount of metadata properties that are set
        @sideeffect(
            response_model=ExamplePassthroughModel,
            reload=tuple([ExampleRenderModel.value_a]),
        )
        def sideeffect_and_return_data(self):
            return dict(
                first_name="John",
            )

    metadata = get_function_metadata(TestController.sideeffect_and_return_data)
    assert metadata.action_type == FunctionActionType.SIDEEFFECT
    assert metadata.get_passthrough_model() == ExamplePassthroughModel
    assert metadata.function_name == "sideeffect_and_return_data"
    assert metadata.reload_states == tuple([ExampleRenderModel.value_a])
    assert metadata.render_model is None
    assert metadata.url is None
    assert metadata.return_model is None
    assert metadata.render_router is None
