from functools import wraps
from typing import Callable, Type, overload

from pydantic import BaseModel

from filzl.actions.fields import FunctionActionType, init_function_metadata


@overload
def passthrough(
    response_model: Type[BaseModel] | None = None,
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

    def decorator_with_args(response_model: Type[BaseModel] | None):
        def wrapper(func: Callable):
            @wraps(func)
            def inner(self, *func_args, **func_kwargs):
                return func(self, *func_args, **func_kwargs)

            metadata = init_function_metadata(inner, FunctionActionType.PASSTHROUGH)
            metadata.passthrough_model = response_model
            return inner

        return wrapper

    if args and callable(args[0]):
        # It's used as @sideeffect without arguments
        func = args[0]
        return decorator_with_args(None)(func)
    else:
        # It's used as @sideeffect(xyz=2) with arguments
        return decorator_with_args(*args, **kwargs)
