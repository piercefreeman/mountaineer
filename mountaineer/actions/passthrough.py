import collections
from enum import Enum
from functools import wraps
from inspect import isawaitable, isclass
from typing import (
    TYPE_CHECKING,
    Any,
    AsyncIterator,
    Callable,
    Iterator,
    Type,
    get_args,
    get_origin,
    overload,
)

from pydantic import BaseModel

from mountaineer.actions.fields import (
    FunctionActionType,
    handle_explicit_responses,
    init_function_metadata,
)
from mountaineer.exceptions import APIException

if TYPE_CHECKING:
    from mountaineer.controller import ControllerBase


class ResponseModelType(Enum):
    SINGLE_RESPONSE = "SINGLE_RESPONSE"
    ITERATOR_RESPONSE = "ITERATOR_RESPONSE"


@overload
def passthrough(
    *,
    response_model: Type[BaseModel] | None = None,
    exception_models: list[Type[APIException]] | None = None,
) -> Callable[[Callable], Callable]:
    ...


@overload
def passthrough(
    *,
    # Support for server-event generators
    response_model: Iterator[Type[BaseModel]]
    | AsyncIterator[Type[BaseModel]]
    | None = None,
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
        response_model: Type[BaseModel]
        | Iterator[Type[BaseModel]]
        | AsyncIterator[Type[BaseModel]]
        | None,
        exception_models: list[Type[APIException]] | None,
    ):
        def wrapper(func: Callable):
            @wraps(func)
            async def inner(self: "ControllerBase", *func_args, **func_kwargs):
                response = func(self, *func_args, **func_kwargs)
                if isawaitable(response):
                    response = await response
                return handle_explicit_responses(dict(passthrough=response))

            passthrough_model, response_type = extract_model_from_decorated_types(
                response_model
            )

            metadata = init_function_metadata(inner, FunctionActionType.PASSTHROUGH)
            metadata.passthrough_model = passthrough_model
            metadata.exception_models = exception_models
            metadata.is_iterator = response_type == ResponseModelType.ITERATOR_RESPONSE
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


def extract_model_from_decorated_types(
    type_hint: Any,
) -> tuple[Type[BaseModel] | None, ResponseModelType]:
    """
    Support response_model typehints like Iterator[Type[BaseModel]] and AsyncIterator[Type[BaseModel]].

    """
    origin_type = get_origin(type_hint)

    if type_hint is None:
        return None, ResponseModelType.SINGLE_RESPONSE
    elif isclass(type_hint) and issubclass(type_hint, BaseModel):
        return type_hint, ResponseModelType.SINGLE_RESPONSE
    elif origin_type in (
        # At runtime our types are actually instantiated as collections.abc objects
        collections.abc.Iterator,
        collections.abc.AsyncIterator,
    ):
        args = get_args(type_hint)
        if args and issubclass(args[0], BaseModel):
            return args[0], ResponseModelType.ITERATOR_RESPONSE

    raise ValueError(f"Invalid response_model typehint: {type_hint}")
