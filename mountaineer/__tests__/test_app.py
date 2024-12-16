from contextlib import asynccontextmanager
from inspect import Parameter, signature
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi import APIRouter, FastAPI, Request, status
from fastapi.exceptions import RequestValidationError as RequestValidationErrorRaw
from fastapi.responses import RedirectResponse
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from pydantic import BaseModel, ValidationError

from mountaineer.app import AppController, ControllerDefinition
from mountaineer.config import ConfigBase
from mountaineer.controller import ControllerBase
from mountaineer.controller_layout import LayoutControllerBase
from mountaineer.exceptions import (
    APIException,
    RequestValidationError,
    RequestValidationFailure,
)
from mountaineer.render import Metadata, RenderBase


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


def test_validates_layouts_exclude_urls():
    """
    The app controller should reject the registration of layouts that specify
    a url.

    """

    class TestLayoutController(LayoutControllerBase):
        # Not allowed, but might typehint correctly because the ControllerBase
        # superclass supports it.
        url = "/layout_url"
        view_path = "/test.tsx"

        async def render(self) -> None:
            pass

    app_controller = AppController(view_root=Path(""))
    with pytest.raises(ValueError, match="are not directly mountable to the router"):
        app_controller.register(TestLayoutController())


def test_format_exception_model():
    class ExampleException(APIException):
        status_code = 401
        value: str

    app = AppController(view_root=Path(""))
    formatted_exception = app._format_exception_model(ExampleException)

    assert formatted_exception.status_code == 401
    assert formatted_exception.schema_name == "ExampleException"
    assert (
        formatted_exception.schema_name_long
        == "mountaineer.__tests__.test_app.ExampleException"
    )
    assert set(formatted_exception.schema_value["required"]) == {
        "value",
        # Inherited from the superclass
        "status_code",
        "detail",
        "headers",
    }


def test_view_root_from_config(tmp_path: Path):
    class MockConfig(ConfigBase):
        PACKAGE: str | None = "test_webapp"

    # Simulate a package with a views directory
    (tmp_path / "views").mkdir()

    with patch("mountaineer.app.resolve_package_path") as mock_resolve_package_path:
        mock_resolve_package_path.return_value = tmp_path

        app = AppController(config=MockConfig())
        assert app._view_root == tmp_path / "views"

        assert mock_resolve_package_path.call_count == 1
        assert mock_resolve_package_path.call_args[0] == ("test_webapp",)


def test_passthrough_fastapi_args():
    did_run_lifespan = False

    @asynccontextmanager
    async def app_lifespan(app: FastAPI):
        nonlocal did_run_lifespan
        did_run_lifespan = True
        yield

    app = AppController(view_root=Path(""), fastapi_args=dict(lifespan=app_lifespan))

    with TestClient(app.app):
        assert did_run_lifespan


def test_unique_controller_names():
    def make_controller(unique_url: str):
        class ExampleController(ControllerBase):
            url = unique_url
            view_path = unique_url

            def render(self) -> None:
                pass

        return ExampleController

    app = AppController(view_root=Path(""))
    app.register(make_controller("/example")())

    with pytest.raises(ValueError, match="already registered"):
        app.register(make_controller("/example2")())


class TargetController(ControllerBase):
    url = "/target"

    async def render(self) -> None:
        pass


class ReferenceController(ControllerBase):
    url = "/reference"

    async def render(self) -> None:
        pass


def test_merge_render_signatures():
    def target_fn(a: int, b: int):
        pass

    # Partial overlap with (a) and inclusion of a new variable
    def reference_fn(a: int, c: int):
        pass

    app = AppController(view_root=Path(""))

    target_definition = ControllerDefinition(
        controller=TargetController(),
        router=APIRouter(),
        view_route=target_fn,
        url_prefix="/target_prefix",
        render_router=APIRouter(),
    )
    reference_definition = ControllerDefinition(
        controller=ReferenceController(),
        router=APIRouter(),
        view_route=reference_fn,
        url_prefix="/reference_prefix",
        render_router=APIRouter(),
    )

    initial_routes = [
        route.path for route in app.app.routes if isinstance(route, APIRoute)
    ]
    assert initial_routes == []

    app.merge_render_signatures(
        target_definition, reference_controller=reference_definition
    )

    assert list(signature(target_definition.view_route).parameters.values()) == [
        Parameter("a", Parameter.POSITIONAL_OR_KEYWORD, annotation=int),
        Parameter("b", Parameter.POSITIONAL_OR_KEYWORD, annotation=int),
        # Items only in the reference function should be included as kwargs
        Parameter("c", Parameter.KEYWORD_ONLY, annotation=int, default=Parameter.empty),
    ]

    # After the merging the signature should be updated, and the app controller should
    # have a new endpoint (since the merging must re-mount)
    final_routes = [
        route.path for route in app.app.routes if isinstance(route, APIRoute)
    ]
    assert final_routes == ["/target"]


def test_merge_render_signatures_conflicting_types():
    """
    If the two functions share a parameter, it must be typehinted with the
    same type in both functions.

    """

    def target_fn(a: int, b: int):
        pass

    # Partial overlap with (a) and inclusion of a new variable
    def reference_fn(a: str, c: int):
        pass

    app = AppController(view_root=Path(""))

    target_definition = ControllerDefinition(
        controller=TargetController(),
        router=APIRouter(),
        view_route=target_fn,
        url_prefix="/target_prefix",
        render_router=APIRouter(),
    )
    reference_definition = ControllerDefinition(
        controller=ReferenceController(),
        router=APIRouter(),
        view_route=reference_fn,
        url_prefix="/reference_prefix",
        render_router=APIRouter(),
    )

    with pytest.raises(TypeError, match="Conflicting types"):
        app.merge_render_signatures(
            target_definition, reference_controller=reference_definition
        )


def test_get_value_mask_for_signature():
    def target_fn(a: int, b: str):
        pass

    values = {
        "a": 1,
        "b": "test",
        "c": "other",
    }

    app = AppController(view_root=Path(""))
    assert app._get_value_mask_for_signature(
        signature(target_fn),
        values,
    ) == {
        "a": 1,
        "b": "test",
    }


class RedirectRender(RenderBase):
    pass


class RedirectController(ControllerBase):
    url = "/redirect"
    view_path = "/test.tsx"

    async def render(self) -> RedirectRender:
        return RedirectRender(
            metadata=Metadata(
                explicit_response=RedirectResponse(
                    status_code=status.HTTP_307_TEMPORARY_REDIRECT, url="/"
                )
            )
        )


def test_explicit_response_metadata():
    app = AppController(view_root=Path(""))
    app.register(RedirectController())

    with TestClient(app.app) as client:
        response = client.get("/redirect", follow_redirects=False)
        assert response.status_code == status.HTTP_307_TEMPORARY_REDIRECT
        assert response.headers["location"] == "/"


@pytest.mark.asyncio
async def test_parse_validation_exception():
    """
    Test that FastAPI validation errors are correctly parsed into our RequestValidationError format.
    """

    class TestModel(BaseModel):
        age: int

    app_controller = AppController(view_root=Path(""))

    # Create a test request with invalid data
    request = Request(
        scope={
            "type": "http",
            "method": "POST",
            "path": "/",
            "headers": [],
        }
    )

    # Create a validation error by trying to validate invalid data
    raw_error: RequestValidationErrorRaw | None = None
    try:
        TestModel.model_validate({"age": "not_a_number"})
    except ValidationError as e:
        raw_error = RequestValidationErrorRaw(errors=e.errors())

    # Test the parsing
    assert raw_error
    with pytest.raises(RequestValidationError) as exc_info:
        await app_controller._parse_validation_exception(request, raw_error)

    exception = exc_info.value
    assert len(exception.internal_model.errors) == 1  # type: ignore
    error = exception.internal_model.errors[0]  # type: ignore
    assert isinstance(error, RequestValidationFailure)

    # Verify the error is parsed correctly
    assert error.error_type == "int_parsing"
    assert error.location == ["age"]
    assert "input should be a valid integer" in error.message.lower()
    assert error.value_input == "not_a_number"
