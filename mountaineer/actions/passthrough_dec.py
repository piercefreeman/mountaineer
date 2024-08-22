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
    Callable,
    Concatenate,
    Coroutine,
    Literal,
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
    SideeffectRawCallable,
    SideeffectResponseBase,
    SideeffectWrappedCallable,
    create_original_fn,
    extract_response_model_from_signature,
    format_final_action_response,
    init_function_metadata,
)
from mountaineer.constants import STREAM_EVENT_TYPE
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
]:
    ...


@overload
def passthrough(
    *,
    raw_response: Literal[True] = True,
) -> Callable[
    [Callable[Concatenate[C, P], RawResponseR | Coroutine[Any, Any, RawResponseR]]],
    SideeffectRawCallable[C, P, RawResponseR],
]:
    ...


@overload
def passthrough(
    func: Callable[Concatenate[C, P], R | Coroutine[Any, Any, R]],
) -> SideeffectWrappedCallable[C, P, R]:
    ...


def passthrough(*args, **kwargs):  # type: ignore
    """
    Only functions that are explicitly marked as actions will be accessable by the frontend. The
    @passthrough decorator indicates that this function should be called by the frontend and will
    return an explicit data payload. It will NOT update the render() state of the frontend.

    Decorate functions within your ControllerBase that you want to expose. Each of these functions should specify
    a return type. Normal passthrough endpoints can return with either a `None`, a `BaseModel` object, or a
    `JSONResponse` if you need full flexibility on return headers and content structure.

    If you do return a JSONResponse note that we will handle the merging of the response for you - so
    on the client side you will still access your endpoint contents with:

    ```typescript
    const response = await serverState.my_action({});
    console.log(response.passthrough);
    ```

    Usage:

    ```python
    from pydantic import BaseModel

    class ResponseModel(BaseModel):
        pass

    class MyController(ControllerBase):
        @passthrough
        async def my_action(self) -> ResponseModel:
            ...
    ```

    :param exception_models: List of APIException subclasses that this function is known
        to throw. These will be parsed and available to frontend clients.
    :type exception_models: list[Type[APIException]] | None

    :param raw_response: If specified, you can return a generic fastapi.Response object. There's
        no constraint this endpoint returns JSON - you can return html or a custom protocol. This
        lets you treat this API as a generic POST endpoint for you to fully control the output.
    :type raw_response: bool

    :return: The response model to use for this endpoint. If a BaseModel is not provided (you pass
        a dictionary or a SQLModel object ofr instance), we will try to convert the response object
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

            @wraps(func)
            async def inner(self: "ControllerBase", *func_args, **func_kwargs):
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

            metadata = init_function_metadata(inner, FunctionActionType.PASSTHROUGH)
            metadata.passthrough_model = passthrough_model
            metadata.exception_models = exception_models
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
