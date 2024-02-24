from re import sub as re_sub
from typing import Callable

import pytest
from fastapi import APIRouter
from fastapi.openapi.utils import get_openapi

from mountaineer.client_builder.build_links import OpenAPIToTypescriptLinkConverter


def view_endpoint_regular():
    pass


def view_endpoint_path_params(path_a: str, path_b: int):
    pass


def view_endpoint_query_params(query_a: str, query_b: int | None = None):
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
                    query_b
                }:{
                    query_a: string,
                    query_b?: null | number
                }) => {
                    const url = `/query_params`;
                    const queryParameters: Record<string,any> = {
                        query_a,
                        query_b
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
