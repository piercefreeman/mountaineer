from functools import wraps
from inspect import isawaitable
from typing import TYPE_CHECKING, Callable, Type, overload

from pydantic import BaseModel

from mountaineer.actions.fields import (
    FunctionActionType,
    handle_explicit_responses,
    init_function_metadata,
)
from mountaineer.exceptions import APIException

if TYPE_CHECKING:
    from mountaineer.controller import ControllerBase


@overload
def passthrough(
    *,
    response_model: Type[BaseModel] | None = None,
    exception_models: list[Type[APIException]] | None = None,
) -> Callable[[Callable], Callable]:
    ...


@overload
def passthrough(func: Callable) -> Callable:
    ...


def passthrough(*args, **kwargs):
    """
    By default, we mask out function return values to avoid leaking any unintended data to client applications. This
    decorator marks a function .

    :response_model: Like in FastAPI, the response model to use for this endpoint. If not provided, will
        try to convert the response object into the proper JSON response as-is.

    """

    def decorator_with_args(
        response_model: Type[BaseModel] | None,
        exception_models: list[Type[APIException]] | None,
    ):
        def wrapper(func: Callable):
            @wraps(func)
            async def inner(self: "ControllerBase", *func_args, **func_kwargs):
                response = func(self, *func_args, **func_kwargs)
                if isawaitable(response):
                    response = await response
                return handle_explicit_responses(dict(passthrough=response))

            metadata = init_function_metadata(inner, FunctionActionType.PASSTHROUGH)
            metadata.passthrough_model = response_model
            metadata.exception_models = exception_models
            return inner

        return wrapper

    if args and callable(args[0]):
        # It's used as @sideeffect without arguments
        func = args[0]
        return decorator_with_args(None, None)(func)
    else:
        # It's used as @passthrough(xyz=2) with arguments
        return decorator_with_args(
            response_model=kwargs.get("response_model"),
            exception_models=kwargs.get("exception_models"),
        )
