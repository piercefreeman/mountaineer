from pydantic.main import BaseModel

from filzl.actions.fields import FunctionActionType, get_function_metadata
from filzl.actions.passthrough import passthrough
from filzl.annotation_helpers import FilzlUnsetValue
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
    assert isinstance(metadata.reload_states, FilzlUnsetValue)
    assert isinstance(metadata.render_model, FilzlUnsetValue)
    assert isinstance(metadata.url, FilzlUnsetValue)
    assert isinstance(metadata.return_model, FilzlUnsetValue)
    assert isinstance(metadata.render_router, FilzlUnsetValue)
