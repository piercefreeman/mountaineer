from inspect import ismethod
from filzl.render import FieldClassDefinition, RenderBase
from typing import Callable, Type
from functools import wraps
from pydantic import BaseModel
from enum import Enum


class FunctionActionType(Enum):
    RENDER = "render"
    SIDEEFFECT = "sideeffect"
    PASSTHROUGH = "passthrough"


class FunctionMetadata(BaseModel):
    function_name: str
    action_type: FunctionActionType
    reload_states: tuple[FieldClassDefinition, ...] | None = None
    render_model: Type[RenderBase] | None = None


METADATA_ATTRIBUTE = "_filzl_metadata"


def init_function_metadata(raw_fn: Callable, action_type: FunctionActionType):
    fn = raw_fn.__func__ if ismethod(raw_fn) else raw_fn
    function_name = fn.__name__
    metadata = FunctionMetadata(function_name=function_name, action_type=action_type)
    setattr(fn, METADATA_ATTRIBUTE, metadata)
    return metadata


def sideeffect(*args, **kwargs):
    """
    Mark a function as causing a sideeffect to the data. This will force a reload of the full (or partial) server state
    and sync these changes down to the client page.

    :reload: If provided, will ONLY reload these fields. By default will reload all fields. Otherwise, why
        specify a sideeffect at all?

    """

    def decorator_with_args(reload: tuple[FieldClassDefinition, ...]):
        def wrapper(func: Callable):
            @wraps(func)
            def inner(self, *func_args, **func_kwargs):
                return func(self, *func_args, **func_kwargs)

            metadata = init_function_metadata(inner, FunctionActionType.SIDEEFFECT)
            metadata.reload_states = reload
            return inner

        return wrapper

    if args and callable(args[0]):
        # It's used as @sideeffect without arguments
        func = args[0]
        return decorator_with_args(())(func)
    else:
        # It's used as @sideeffect(xyz=2) with arguments
        return decorator_with_args(*args, **kwargs)


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

            init_function_metadata(inner, FunctionActionType.PASSTHROUGH)
            return inner

        return wrapper

    if args and callable(args[0]):
        # It's used as @sideeffect without arguments
        func = args[0]
        return decorator_with_args(None)(func)
    else:
        # It's used as @sideeffect(xyz=2) with arguments
        return decorator_with_args(*args, **kwargs)
