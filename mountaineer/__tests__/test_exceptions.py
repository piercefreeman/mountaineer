import pytest
from pydantic import Field, ValidationError

from mountaineer.exceptions import APIException


def test_exceptions():
    class Test402(APIException):
        status_code = 402
        detail = "Test 402"
        custom_value: str

    exception = Test402(custom_value="custom")

    # Make sure that we pass along the metadata to the exception superclass
    assert exception.status_code == 402
    assert exception.detail == "Test 402"
    assert exception.headers == {}
    # assert exception.custom_value == "custom"

    # Test its internal value
    assert exception.internal_model.status_code == 402
    assert exception.internal_model.detail == "Test 402"

    # We need to ignore typing here because custom_value is dynamically
    # added to the pydantic schema via create_model
    # It won't typehint correctly but it will be available at runtime
    # which is all we care about
    assert exception.internal_model.custom_value == "custom"  # type: ignore


def test_internal_model_constructor():
    """
    Test the translation of the APIException to an internal Pydantic model with
    the correct internal types.

    """

    class Test402(APIException):
        status_code = 402
        detail = "Test 402"
        custom_value: str

    assert not Test402.InternalModel.model_fields["status_code"].is_required()
    assert not Test402.InternalModel.model_fields["detail"].is_required()
    assert Test402.InternalModel.model_fields["custom_value"].is_required()


def test_exceptions_validate_values():
    class Test402(APIException):
        status_code = 402
        detail = "Test 402"
        custom_value: int = Field(lt=10)

    with pytest.raises(ValidationError):
        Test402(custom_value=20)
