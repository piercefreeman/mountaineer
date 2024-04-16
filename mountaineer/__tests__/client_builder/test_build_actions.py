from datetime import datetime
from re import sub as re_sub
from uuid import UUID

import pytest
from fastapi import APIRouter
from fastapi.openapi.utils import get_openapi
from pydantic import BaseModel

from mountaineer.client_builder.build_actions import OpenAPIToTypescriptActionConverter
from mountaineer.client_builder.openapi import (
    ActionDefinition,
    ActionType,
    ContentBodyDefinition,
    ContentDefinition,
    OpenAPIProperty,
    OpenAPISchemaType,
    ParameterLocationType,
    URLParameterDefinition,
)
from mountaineer.constants import STREAM_EVENT_TYPE


def test_convert():
    """
    Test the conversion of a full OpenAPI schema. We make sure that the pipeline
    ends with the expected multiple fields and import, but we don't test
    the exact code generation.

    """

    class ExampleModel(BaseModel):
        pass

    class ExampleResponseModel(BaseModel):
        pass

    def fn1(payload: ExampleModel):
        pass

    def fn2():
        pass

    # Each function needs a response model because we expect that all @sideeffect
    # and @passthrough functions will have an automatically defined response model
    router = APIRouter()
    router.post("/fn1", response_model=ExampleResponseModel)(fn1)
    router.post("/fn2", response_model=ExampleResponseModel)(fn2)

    builder = OpenAPIToTypescriptActionConverter()
    openapi_spec = get_openapi(title="", version="", routes=router.routes)
    fetch_definitions, import_definitions = builder.convert(openapi_spec)

    # Returns the error classes alongside the route definitions
    assert set(fetch_definitions.keys()) == {"fn1", "fn2", "HTTPValidationError"}
    assert set(import_definitions) == {
        "ExampleModel",
        "ExampleResponseModel",
        "HTTPValidationError",
    }


EXAMPLE_REQUEST_BODY = ContentBodyDefinition(
    content_type="application/json",
    content_schema=ContentDefinition.from_meta(
        schema_ref=ContentDefinition.Reference.from_meta(
            ref="#/components/schemas/ExampleModel"
        )
    ),
)

EXAMPLE_RESPONSE_200 = ContentBodyDefinition(
    content_type="application/json",
    content_schema=ContentDefinition.from_meta(
        schema_ref=ContentDefinition.Reference.from_meta(
            ref="#/components/schemas/ExampleResponseModel"
        )
    ),
)

EXAMPLE_RESPONSE_400 = ContentBodyDefinition(
    content_type="application/json",
    content_schema=ContentDefinition.from_meta(
        schema_ref=ContentDefinition.Reference.from_meta(
            ref="#/components/schemas/HTTPValidationError"
        )
    ),
)


@pytest.mark.parametrize(
    "method_name,url,definition,expected_function,expected_imports",
    [
        # Request/response based body
        (
            "my_method_fn",
            "/testing/url",
            ActionDefinition(
                action_type=ActionType.POST,
                summary="",
                operationId="",
                requestBody=EXAMPLE_REQUEST_BODY,
                responses={
                    "200": EXAMPLE_RESPONSE_200,
                    "422": EXAMPLE_RESPONSE_400,
                },
            ),
            (
                """
                export const my_method_fn = (
                    {requestBody}: {requestBody: ExampleModel}
                ): Promise<ExampleResponseModel> => {
                    return __request({
                        'method': 'POST',
                        'url': '/testing/url',
                        'errors': {
                            422: HTTPValidationErrorException
                        },
                        'body': requestBody,
                        'mediaType': 'application/json'
                    });
                }
                """
            ),
            [
                "ExampleModel",
                "ExampleResponseModel",
            ],
        ),
        # No request body parameter
        (
            "my_method_fn",
            "/testing/url",
            ActionDefinition(
                action_type=ActionType.POST,
                summary="",
                operationId="",
                requestBody=None,
                responses={
                    "200": EXAMPLE_RESPONSE_200,
                    "422": EXAMPLE_RESPONSE_400,
                },
            ),
            (
                """
                export const my_method_fn = (): Promise<ExampleResponseModel> => {
                    return __request({
                        'method': 'POST',
                        'url': '/testing/url',
                        'errors': {
                            422: HTTPValidationErrorException
                        }
                    });
                }
                """
            ),
            [
                "ExampleResponseModel",
            ],
        ),
        # Path and query parameters
        (
            "my_method_fn",
            "/testing/{item_id}",
            ActionDefinition(
                action_type=ActionType.POST,
                summary="",
                operationId="",
                requestBody=EXAMPLE_REQUEST_BODY,
                responses={
                    "200": EXAMPLE_RESPONSE_200,
                },
                parameters=[
                    # All path parameters are required
                    URLParameterDefinition.from_meta(
                        name="item_id",
                        schema_ref=OpenAPIProperty.from_meta(
                            title="",
                            variable_type=OpenAPISchemaType.STRING,
                        ),
                        in_location=ParameterLocationType.PATH,
                        required=True,
                    ),
                    # Required query parameter
                    URLParameterDefinition.from_meta(
                        name="query_param_required_id",
                        schema_ref=OpenAPIProperty.from_meta(
                            title="",
                            variable_type=OpenAPISchemaType.STRING,
                        ),
                        in_location=ParameterLocationType.QUERY,
                        required=True,
                    ),
                    # Cookies and headers should be skipped
                    URLParameterDefinition.from_meta(
                        name="auth_cookie",
                        schema_ref=OpenAPIProperty.from_meta(
                            title="",
                            variable_type=OpenAPISchemaType.STRING,
                        ),
                        in_location=ParameterLocationType.COOKIE,
                        required=True,
                    ),
                    URLParameterDefinition.from_meta(
                        name="auth_header",
                        schema_ref=OpenAPIProperty.from_meta(
                            title="",
                            variable_type=OpenAPISchemaType.STRING,
                        ),
                        in_location=ParameterLocationType.HEADER,
                        required=True,
                    ),
                    # Optional query parameter
                    URLParameterDefinition.from_meta(
                        name="query_param_optional_id",
                        schema_ref=OpenAPIProperty.from_meta(
                            title="",
                            variable_type=OpenAPISchemaType.STRING,
                        ),
                        in_location=ParameterLocationType.QUERY,
                        required=False,
                    ),
                ],
            ),
            (
                """
                export const my_method_fn = (
                    {
                        item_id,
                        query_param_required_id,
                        query_param_optional_id,
                        requestBody
                    }: {
                        item_id: string,
                        query_param_required_id: string,
                        query_param_optional_id?: string,
                        requestBody: ExampleModel
                    }
                ): Promise<ExampleResponseModel> => {
                    return __request({
                        'method': 'POST',
                        'url': '/testing/{item_id}',
                        'path': {
                            item_id
                        },
                        'query': {
                            query_param_required_id,
                            query_param_optional_id
                        },
                        'body': requestBody,
                        'mediaType': 'application/json'
                    });
                }
                """
            ),
            [
                "ExampleModel",
                "ExampleResponseModel",
            ],
        ),
    ],
)
def test_build_action(
    url: str,
    method_name: str,
    definition: ActionDefinition,
    expected_function: str,
    expected_imports: list[str],
):
    """
    Test the building of a single action fetch body.
    """
    builder = OpenAPIToTypescriptActionConverter()
    built_function, build_imports = builder.build_action(url, definition, method_name)

    # Exact match for function contents
    assert re_sub(r"\s+", "", built_function) == re_sub(r"\s+", "", expected_function)

    # Order doesn't matter in the imports. We assume they're all coming from the locally defined
    # /models.ts source file.
    assert set(build_imports) == set(expected_imports)


@pytest.mark.parametrize(
    "method_name,url,definition,expected_function,expected_imports",
    [
        (
            "my_method_fn",
            "/testing/url",
            ActionDefinition(
                action_type=ActionType.POST,
                summary="",
                operationId="",
                requestBody=EXAMPLE_REQUEST_BODY,
                responses={
                    "200": EXAMPLE_RESPONSE_200,
                    "422": EXAMPLE_RESPONSE_400,
                },
                media_type=STREAM_EVENT_TYPE,
            ),
            (
                """
                export const my_method_fn = (
                    {requestBody}: {requestBody: ExampleModel}
                ): Promise<AsyncGenerator<ExampleResponseModel, void, unknown>> => {
                    return __request({
                        'method': 'POST',
                        'url': '/testing/url',
                        'errors': {
                            422: HTTPValidationErrorException
                        },
                        'body': requestBody,
                        'mediaType': 'application/json',
                        'eventStreamResponse': true
                    });
                }
                """
            ),
            [
                "ExampleModel",
                "ExampleResponseModel",
            ],
        ),
    ],
)
def test_build_server_side_event_action(
    url: str,
    method_name: str,
    definition: ActionDefinition,
    expected_function: str,
    expected_imports: list[str],
):
    builder = OpenAPIToTypescriptActionConverter()
    built_function, build_imports = builder.build_action(url, definition, method_name)
    assert re_sub(r"\s+", "", built_function) == re_sub(r"\s+", "", expected_function)
    assert set(build_imports) == set(expected_imports)


@pytest.mark.parametrize(
    "method_name,url,definition,expected_function,expected_imports",
    [
        (
            "my_method_fn",
            "/testing/url",
            ActionDefinition(
                action_type=ActionType.POST,
                summary="",
                operationId="",
                requestBody=EXAMPLE_REQUEST_BODY,
                responses={
                    "200": ContentBodyDefinition(
                        content_type="application/json",
                        content_schema=ContentDefinition.from_meta(
                            schema_ref=ContentDefinition.Reference.from_meta(
                                # We won't have a response_model for raw responses
                                ref=""
                            )
                        ),
                    ),
                    "422": EXAMPLE_RESPONSE_400,
                },
                is_raw_response=True,
            ),
            (
                """
                export const my_method_fn = (
                    {requestBody}: {requestBody: ExampleModel}
                ): Promise<Response> => {
                    return __request({
                        'method': 'POST',
                        'url': '/testing/url',
                        'errors': {
                            422: HTTPValidationErrorException
                        },
                        'body': requestBody,
                        'mediaType': 'application/json',
                        'outputFormat': 'raw'
                    });
                }
                """
            ),
            [
                "ExampleModel",
            ],
        ),
    ],
)
def test_build_raw_response_action(
    url: str,
    method_name: str,
    definition: ActionDefinition,
    expected_function: str,
    expected_imports: list[str],
):
    builder = OpenAPIToTypescriptActionConverter()
    built_function, build_imports = builder.build_action(url, definition, method_name)
    assert re_sub(r"\s+", "", built_function) == re_sub(r"\s+", "", expected_function)
    assert set(build_imports) == set(expected_imports)


AnyType = None | bool | str | int | datetime | UUID
DictParamItem = dict[str, AnyType]


def test_build_invalid_action_api():
    """
    Ensure that we throw an error if the user has provided a schema payload
    that is technically valid, but doesn't allow typehinting with pydantic. All non-raw
    JSON requests should be Pydantic methods.

    https://github.com/piercefreeman/mountaineer/issues/94

    """

    def fn1(payload: DictParamItem, item_id: str, other_id: str) -> None:
        pass

    router = APIRouter()
    router.post("/fn1")(fn1)

    builder = OpenAPIToTypescriptActionConverter()
    openapi_spec = get_openapi(title="", version="", routes=router.routes)

    with pytest.raises(ValueError):
        builder.convert(openapi_spec)
