from pathlib import Path

import pytest
from pydantic import BaseModel

from filzl.actions import passthrough
from filzl.app import AppController
from filzl.client_builder.openapi import OpenAPIDefinition
from filzl.controller import ControllerBase
from filzl.exceptions import APIException


def test_requires_render_return_value():
    """
    The AppController is in charge of validating our render return value. Since renders are not
    decorated, the best place to validate is during a mount.

    """

    class TestControllerWithoutRenderMarkup(ControllerBase):
        url = "/"
        view_path = "/page.tsx"

        def render(self):
            return None

    class TestControllerWithRenderMarkup(ControllerBase):
        url = "/"
        view_path = "/page.tsx"

        def render(self) -> None:
            return None

    app = AppController(view_root=Path(""))
    with pytest.raises(ValueError, match="must have a return type annotation"):
        app.register(TestControllerWithoutRenderMarkup())

    app.register(TestControllerWithRenderMarkup())


def test_generate_openapi():
    class ExampleSubModel(BaseModel):
        sub_value: str

    class ExampleException(APIException):
        status_code = 401
        invalid_reason: str
        sub_model: ExampleSubModel

    class ExampleController(ControllerBase):
        url = "/example"
        view_path = "/example.tsx"

        def render(self) -> None:
            pass

        @passthrough(exception_models=[ExampleException])
        def test_exception_action(self):
            pass

    app = AppController(view_root=Path(""))
    app.register(ExampleController())
    openapi_spec = app.generate_openapi()
    openapi_definition = OpenAPIDefinition(**openapi_spec)

    assert openapi_definition.components.schemas.keys() == {
        "TestExceptionActionResponse",
        "ExampleException",
        "ExampleSubModel",
    }
