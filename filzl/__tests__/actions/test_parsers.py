from fastapi import Request
from filzl.actions.parsers import parse_fastapi_function, ParsedSignature
from pydantic import BaseModel
from typing import Annotated, Optional
from fastapi import Query

def test_parse_fastapi_function():
    class RequestModel(BaseModel):
        a: str

    def test_function(
        # Include a dependency injection parameter to test that it is ignored
        request: Request,
        payload: RequestModel,
        item_id: int,
        query_param_1: str,
        query_param_2: Annotated[str | None, Query(max_length=50)] = None
    ):
        pass

    parsed_fn = parse_fastapi_function(test_function, "/test/{item_id}")
    assert parsed_fn == ParsedSignature(
        post_payloads=[RequestModel],
        url_queries=[("query_param_1", str), ("query_param_2", Optional[str])],
        url_arguments=[("item_id", int)],
    )
