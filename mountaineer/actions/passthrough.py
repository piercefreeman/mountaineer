from functools import wraps
from inspect import (
    isasyncgen,
    isasyncgenfunction,
    isawaitable,
    isgeneratorfunction,
)
from json import dumps as json_dumps
from typing import (
    TYPE_CHECKING,
    Any,
    AsyncIterator,
    Awaitable,
    Callable,
    Coroutine,
    ParamSpec,
    Type,
    TypeVar,
    overload,
)

from fastapi.responses import JSONResponse, Response, StreamingResponse
from pydantic import BaseModel

from mountaineer.actions.fields import (
    FunctionActionType,
    ResponseModelType,
    extract_response_model_from_signature,
    handle_explicit_responses,
    init_function_metadata,
)
from mountaineer.constants import STREAM_EVENT_TYPE
from mountaineer.exceptions import APIException

if TYPE_CHECKING:
    from mountaineer.controller import ControllerBase

P = ParamSpec("P")
R = TypeVar("R", bound=BaseModel | AsyncIterator[BaseModel] | JSONResponse | None)

RawResponseR = TypeVar("RawResponseR", bound=Response)


@overload
def passthrough(  # type: ignore
    *,
    response_model: Type[BaseModel] | None = None,
    exception_models: list[Type[APIException]] | None = None,
) -> Callable[[Callable[P, R | Coroutine[Any, Any, R]]], Callable[P, Awaitable[R]]]:
    ...


@overload
def passthrough(
    *,
    raw_response: bool = True,
) -> Callable[
    [Callable[P, RawResponseR | Coroutine[Any, Any, RawResponseR]]],
    Callable[P, Awaitable[RawResponseR]],
]:
    ...


@overload
def passthrough(
    func: Callable[P, R | Coroutine[Any, Any, R]],
) -> Callable[P, Awaitable[R]]:
    ...


def passthrough(*args, **kwargs):  # type: ignore
    """
    By default, we mask out function return values to avoid leaking any unintended data to client applications. This
    decorator marks a function .

    :response_model: Like in FastAPI, the response model to use for this endpoint. If not provided, will
        try to convert the response object into the proper JSON response as-is.

    """

    def decorator_with_args(
        response_model: Type[BaseModel] | None,
        exception_models: list[Type[APIException]] | None,
        raw_response: bool | None,
    ):
        def wrapper(func: Callable):
            passthrough_model, response_type = extract_response_model_from_signature(
                func, response_model
            )

            # Ensure our function is valid as early as possible
            # Since sync functions are blocking (unless they're run in a separate thread pool), we require long-running
            # functions to be async
            if isgeneratorfunction(func):
                raise ValueError(
                    f"Only async generators are supported: Define {func} as `async def`"
                )

            # The user has defined a generator but not a response_model
            # The frontend builder needs a response model to be able to determine the type
            if (
                isasyncgenfunction(func)
                and response_type != ResponseModelType.ITERATOR_RESPONSE
            ):
                raise ValueError(
                    f"Async generator {func} must have a response_model of type AsyncIterator[BaseModel]"
                )

            @wraps(func)
            async def inner(self: "ControllerBase", *func_args, **func_kwargs):
                response = func(self, *func_args, **func_kwargs)
                if isawaitable(response):
                    response = await response

                if raw_response:
                    return response

                if isasyncgen(response):
                    return wrap_passthrough_generator(response)

                return handle_explicit_responses(dict(passthrough=response))

            metadata = init_function_metadata(inner, FunctionActionType.PASSTHROUGH)
            metadata.passthrough_model = passthrough_model
            metadata.exception_models = exception_models
            metadata.is_raw_response = raw_response or False
            metadata.media_type = (
                STREAM_EVENT_TYPE
                if response_type == ResponseModelType.ITERATOR_RESPONSE
                else None
            )
            return inner

        return wrapper

    if args and callable(args[0]):
        # It's used as @sideeffect without arguments
        func = args[0]
        return decorator_with_args(None, None, None)(func)
    else:
        # It's used as @passthrough(xyz=2) with arguments
        return decorator_with_args(
            response_model=kwargs.get("response_model"),
            exception_models=kwargs.get("exception_models"),
            raw_response=kwargs.get("raw_response"),
        )


def wrap_passthrough_generator(generator: AsyncIterator[BaseModel]):
    """
    Simple function to convert a generator of Pydantic values to a server-event-stream
    of text payloads.

    """

    async def generate():
        async for value in generator:
            json_payload = value.model_dump(mode="json")
            data = json_dumps(dict(passthrough=json_payload))
            yield f"data: {data}\n"

    return StreamingResponse(generate(), media_type=STREAM_EVENT_TYPE)
