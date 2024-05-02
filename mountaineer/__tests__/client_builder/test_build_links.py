from re import sub as re_sub
from typing import Annotated, Callable
from uuid import UUID

import pytest
from fastapi import APIRouter, Query
from fastapi.openapi.utils import get_openapi

from mountaineer.client_builder.build_links import OpenAPIToTypescriptLinkConverter
from mountaineer.compat import StrEnum


def view_endpoint_regular():
    pass


def view_endpoint_path_params(path_a: str, path_b: int):
    pass


def view_endpoint_query_params(
    query_a: str,
    query_b: int | None = None,
    query_c: Annotated[list[int] | None, Query()] = None,
):
    pass


class RouteType(StrEnum):
    ROUTE_A = "route_a"
    ROUTE_B = "route_b"


def enum_view_url(model_type: RouteType, model_id: UUID):
    """
    Model view paths like /{model_type}/{model_id} where we want a flexible
    string to be captured in the model_type path.

    """
    pass


@pytest.mark.parametrize(
    "url, endpoint, expected_link",
    [
        # Regular view endpoint, no render params
        (
            "/regular/",
            view_endpoint_regular,
            (
                """
                export const getLink = ({}:{}) => {
                    const url = `/regular/`;
                    const queryParameters: Record<string,any> = {};
                    const pathParameters: Record<string,any> = {};
                    return __getLink({
                        rawUrl: url,
                        queryParameters,
                        pathParameters
                    });
                };
                """
            ),
        ),
        # View endpoint with path params
        (
            "/url_params/{path_a}/{path_b}",
            view_endpoint_path_params,
            (
                """
                export const getLink = ({
                    path_a,
                    path_b
                }:{
                    path_a: string,
                    path_b: number
                }) => {
                    const url = `/url_params/{path_a}/{path_b}`;
                    const queryParameters: Record<string,any> = {};
                    const pathParameters: Record<string,any> = {
                        path_a,
                        path_b
                    };
                    return __getLink({
                        rawUrl: url,
                        queryParameters,
                        pathParameters
                    });
                };
                """
            ),
        ),
        # View endpoint with query params
        (
            "/query_params",
            view_endpoint_query_params,
            (
                """
                export const getLink = ({
                    query_a,
                    query_b,
                    query_c
                }:{
                    query_a: string,
                    query_b?: null | number,
                    query_c?: Array<number> | null
                }) => {
                    const url = `/query_params`;
                    const queryParameters: Record<string,any> = {
                        query_a,
                        query_b,
                        query_c
                    };
                    const pathParameters: Record<string,any> = {};
                    return __getLink({
                        rawUrl: url,
                        queryParameters,
                        pathParameters
                    });
                };
                """
            ),
        ),
        # Path with enum path variables - we should typehint explicitly
        # as the enum based values
        (
            "/enum_view/{model_type}/{model_id}",
            enum_view_url,
            (
                """
                export const getLink = ({
                    model_type,
                    model_id
                }:{
                    model_type: 'route_a' | 'route_b',
                    model_id: string
                }) => {
                    const url = `/enum_view/{model_type}/{model_id}`;
                    const queryParameters: Record<string,any> = {};
                    const pathParameters: Record<string,any> = {
                        model_type,
                        model_id
                    };
                    return __getLink({
                        rawUrl: url,
                        queryParameters,
                        pathParameters
                    });
                };
                """
            ),
        ),
    ],
)
def test_convert(url: str, endpoint: Callable, expected_link: str):
    # Each function needs a response model because we expect that all @sideeffect
    # and @passthrough functions will have an automatically defined response model
    router = APIRouter()
    router.get(url)(endpoint)

    builder = OpenAPIToTypescriptLinkConverter()
    openapi_spec = get_openapi(title="", version="", routes=router.routes)
    link_fn = builder.convert(openapi_spec)

    assert re_sub(r"\s+", "", link_fn) == re_sub(r"\s+", "", expected_link)
