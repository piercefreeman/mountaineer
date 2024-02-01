from pydantic.main import BaseModel

from filzl.actions.fields import FunctionActionType, get_function_metadata
from filzl.actions.passthrough import passthrough
from filzl.controller import ControllerBase


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
    assert metadata.reload_states is None
    assert metadata.render_model is None
    assert metadata.url is None
    assert metadata.return_model is None
    assert metadata.render_router is None
