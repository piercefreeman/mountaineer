from functools import wraps
from inspect import (
    Parameter,
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
    Callable,
    Concatenate,
    Coroutine,
    Literal,
    ParamSpec,
    Type,
    TypeVar,
    overload,
)

from fastapi import Request
from fastapi.responses import JSONResponse, Response, StreamingResponse
from pydantic import BaseModel

from mountaineer.actions.fields import (
    FunctionActionType,
    ResponseModelType,
    SideeffectRawCallable,
    SideeffectResponseBase,
    SideeffectWrappedCallable,
    create_original_fn,
    extract_response_model_from_signature,
    format_final_action_response,
    init_function_metadata,
)
from mountaineer.constants import STREAM_EVENT_TYPE
from mountaineer.dependencies.base import (
    get_function_dependencies,
    isolate_dependency_only_function,
    strip_depends_from_signature,
)
from mountaineer.exceptions import APIException

if TYPE_CHECKING:
    from mountaineer.controller import ControllerBase

P = ParamSpec("P")
R = TypeVar("R", bound=BaseModel | AsyncIterator[BaseModel] | JSONResponse | None)
C = TypeVar("C")

RawResponseR = TypeVar("RawResponseR", bound=Response)


@overload
def passthrough(  # type: ignore
    *,
    response_model: Type[BaseModel] | None = None,  # Deprecated
    exception_models: list[Type[APIException]] | None = None,
) -> Callable[
    [Callable[Concatenate[C, P], R | Coroutine[Any, Any, R]]],
    SideeffectWrappedCallable[C, P, R],
]: ...


@overload
def passthrough(
    *,
    raw_response: Literal[True] = True,
) -> Callable[
    [Callable[Concatenate[C, P], RawResponseR | Coroutine[Any, Any, RawResponseR]]],
    SideeffectRawCallable[C, P, RawResponseR],
]: ...


@overload
def passthrough(
    func: Callable[Concatenate[C, P], R | Coroutine[Any, Any, R]],
) -> SideeffectWrappedCallable[C, P, R]: ...


def passthrough(*args, **kwargs):  # type: ignore
    """
    Only functions that are explicitly marked as actions will be accessable by the frontend. The
    @passthrough decorator indicates that this function should be called by the frontend and will
    return an explicit data payload. It will NOT update the render() state of the frontend.

    Decorate functions within your ControllerBase that you want to expose. Each of these functions should specify
    a return type. Normal passthrough endpoints can return with either a `None`, a `BaseModel` object, or a
    `JSONResponse` if you need full flexibility on return headers and content structure.

    If you do return a JSONResponse note that we will handle the merging of the response for you - so
    on the client side you will still access your endpoint contents as `response.passthrough`.

    ```typescript {{ sticky: True }}
    const response = await serverState.my_action({
        name: "John Appleseed",
    });
    console.log(response.passthrough.name);
    ```

    ```python {{ sticky: True }}
    from pydantic import BaseModel

    class ResponseModel(BaseModel):
        name: str

    class MyController(ControllerBase):
        @passthrough
        async def my_action(self, name: str) -> ResponseModel:
            return ResponseModel(name=name)
    ```

    :param exception_models: List of APIException subclasses that this function is known
        to throw. These will be parsed and available to frontend clients.
    :type exception_models: list[Type[APIException]] | None

    :param raw_response: If specified, you can return a generic fastapi.Response object. There's
        no constraint this endpoint returns JSON - you can return html or a custom protocol. This
        lets you treat this API as a generic POST endpoint for you to fully control the output.
    :type raw_response: bool

    :return: The response model to use for this endpoint. If a BaseModel is not provided (you pass
        a dictionary or an database object for instance), we will try to convert the response object
        into the proper JSON response based on your typehint.
    :rtype: BaseModel | None | fastapi.JSONResponse

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

            if isasyncgenfunction(func):
                inner = _build_streaming_inner(func)
            else:
                inner = _build_standard_inner(func, raw_response)

            metadata = init_function_metadata(inner, FunctionActionType.PASSTHROUGH)
            metadata.passthrough_model = passthrough_model
            metadata.exception_models += exception_models or []
            metadata.is_raw_response = raw_response or False
            metadata.media_type = (
                STREAM_EVENT_TYPE
                if response_type == ResponseModelType.ITERATOR_RESPONSE
                else None
            )

            inner.original = create_original_fn(func)  # type: ignore
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


def _build_streaming_inner(func: Callable) -> Callable:
    """
    Build the inner wrapper for async generator passthrough endpoints.

    Depends() parameters are stripped from the FastAPI-visible signature and
    resolved manually inside the streaming generator, so they stay alive for
    the full iteration rather than being cleaned up before Starlette starts
    consuming the response.

    """
    dep_fn = isolate_dependency_only_function(func)

    @wraps(func)
    async def inner(self: "ControllerBase", *func_args: Any, **func_kwargs: Any):
        request = func_kwargs.pop("__mountaineer_request__", None)

        async def generate():
            async with get_function_dependencies(
                callable=dep_fn,
                request=request,
            ) as dep_values:
                merged_kwargs = {**func_kwargs, **dep_values}
                async for value in func(self, *func_args, **merged_kwargs):
                    json_payload = value.model_dump(mode="json")
                    data = json_dumps(dict(passthrough=json_payload))
                    yield f"data: {data}\n"

        return StreamingResponse(generate(), media_type=STREAM_EVENT_TYPE)

    # Rewrite the signature FastAPI sees: strip Depends() params,
    # add a Request param so we can forward it for manual DI resolution
    #
    # FastAPI 0.135+ unwraps decorated callables when deciding whether an
    # endpoint is an async generator. If we leave __wrapped__ in place, it sees
    # the original async generator and bypasses this wrapper entirely, treating
    # the StreamingResponse-producing endpoint as a JSONL stream.
    del inner.__wrapped__
    inner.__signature__ = _build_streaming_signature(func)  # type: ignore
    return inner


def _build_standard_inner(func: Callable, raw_response: bool | None) -> Callable:
    """Build the inner wrapper for non-streaming passthrough endpoints."""

    @wraps(func)
    async def inner(self: "ControllerBase", *func_args: Any, **func_kwargs: Any):
        response = func(self, *func_args, **func_kwargs)
        if isawaitable(response):
            response = await response

        if raw_response:
            return response

        if isasyncgen(response):
            return wrap_passthrough_generator(response)

        # Following types ignored to support 3.10
        final_payload: SideeffectResponseBase[Any] = {  # type: ignore
            "passthrough": response,
        }
        return format_final_action_response(final_payload)  # type: ignore

    return inner


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


def _build_streaming_signature(func: Callable):
    """
    Build a signature for the FastAPI-facing wrapper of a streaming async generator.

    Strips all Depends() parameters (they'll be resolved manually inside the generator)
    and adds a Request parameter that gets forwarded as __mountaineer_request__ so the
    manual DI resolution can use it.

    """
    sig = strip_depends_from_signature(func)

    # Add a Request parameter that FastAPI will inject automatically.
    # We use a private name to avoid collisions with user params, and
    # alias it in the wrapper via **func_kwargs.
    request_param = Parameter(
        "__mountaineer_request__",
        kind=Parameter.KEYWORD_ONLY,
        annotation=Request,
    )

    return sig.replace(parameters=[*sig.parameters.values(), request_param])
