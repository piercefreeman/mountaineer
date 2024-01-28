from inspect import Parameter, isclass, signature
from typing import Callable, Type, Optional, Any
from fastapi.params import Depends as DependsParam, Query as QueryParam
from pydantic import BaseModel
from re import findall
from filzl.annotation_helpers import yield_all_subtypes


class ParsedSignature(BaseModel):
    post_payloads: list[Type[BaseModel]]
    url_queries: list[tuple[str, Any]]
    url_arguments: list[tuple[str, Any]]

ALLOWED_QUERY_TYPES = {
    str,
    int,
    float,
    bool,
    None,
}

def extract_url_arguments(url: str) -> list[str]:
    return findall(r"{(.*?)}", url)

def is_dependency_injection(param: Parameter):
    return isinstance(param.default, DependsParam)

def is_query_param(param: Parameter):
    if isinstance(param.default, QueryParam):
        return True
    all_subtypes = set(yield_all_subtypes(param.annotation))
    print("ALL SUBTYPES", all_subtypes)
    return all_subtypes - ALLOWED_QUERY_TYPES == set()

def parse_fastapi_function(func: Callable, endpoint_url: str) -> ParsedSignature:
    sig = signature(func)
    post_payloads : list[Type[BaseModel]] = []
    url_queries : list[tuple[str, Any]] = []
    url_arguments : list[tuple[str, Any]] = []

    path_params = extract_url_arguments(endpoint_url)

    for param_name, param in sig.parameters.items():
        # Invalidation conditions is we can ensure the type is not valid
        if is_dependency_injection(param):
            continue

        if isclass(param.annotation) and issubclass(param.annotation, BaseModel):
            post_payloads.append(param.annotation)
        elif param_name in path_params:
            url_arguments.append((param_name, param.annotation))
        elif is_query_param(param):
            url_queries.append((param_name, param.annotation))

    return ParsedSignature(
        post_payloads=post_payloads,
        url_queries=url_queries,
        url_arguments=url_arguments,
    )
