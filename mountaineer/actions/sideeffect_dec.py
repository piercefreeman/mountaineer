from contextlib import asynccontextmanager
from functools import partial, wraps
from inspect import Parameter, isawaitable, signature
from typing import (
    TYPE_CHECKING,
    Any,
    Callable,
    Concatenate,
    Coroutine,
    ParamSpec,
    Type,
    TypeVar,
    overload,
)
from urllib.parse import urlparse

from fastapi import Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from starlette.routing import Match

from mountaineer.actions.fields import (
    FunctionActionType,
    ResponseModelType,
    SideeffectResponseBase,
    SideeffectWrappedCallable,
    create_original_fn,
    extract_response_model_from_signature,
    format_final_action_response,
    init_function_metadata,
)
from mountaineer.controller_layout import LayoutControllerBase
from mountaineer.cropper import crop_function_for_return_keys
from mountaineer.dependencies import get_function_dependencies
from mountaineer.exceptions import APIException
from mountaineer.render import FieldClassDefinition

if TYPE_CHECKING:
    from mountaineer.controller import ControllerBase

P = ParamSpec("P")
R = TypeVar("R", bound=BaseModel | JSONResponse | None)
C = TypeVar("C")


@overload
def sideeffect(
    *,
    reload: tuple[Any, ...] | None = None,
    response_model: Type[BaseModel] | None = None,  # deprecated
    exception_models: list[Type[APIException]] | None = None,
    experimental_render_reload: bool | None = None,
) -> Callable[
    [Callable[Concatenate[C, P], R | Coroutine[Any, Any, R]]],
    SideeffectWrappedCallable[C, P, R],
]:
    """
    @sideeffect decorator with options.
    """
    ...


@overload
def sideeffect(
    func: Callable[Concatenate[C, P], R | Coroutine[Any, Any, R]],
) -> SideeffectWrappedCallable[C, P, R]:
    """
    Simple @sideeffect, will use default options.
    """
    ...


def sideeffect(*args, **kwargs):  # type: ignore
    """
    Mark a function as causing a sideeffect to the data. This will force a reload of the full (or partial) server state
    and sync these changes down to the client page.

    Like passthroughs, @sideeffect accepts return values of None, BaseModel, or a JSONResponse if you need full flexibility
    on return headers and content structure. Unlike @passthrough, it does not allow you to provide a non-JSON response since we need
    to internally merge it with render() sideeffect update.

    :param exception_models: List of APIException subclasses that this function is known
        to throw. These will be parsed and available to frontend clients.
    :type exception_models: list[Type[APIException]] | None

    :param reload:

        If provided, will ONLY reload these fields on the client side. By default will reload all fields. Otherwise, why
        specify a sideeffect at all? Note that even if this is provided, we will still regenerate a fully full state on the server
        as if render() is called again. This parameter only controls the data that is streamed back to the client in order to help
        reduce bandwidth of data that won't be changed.

    :type reload: tuple[FieldClassDefinition, ...] | None

    :param experimental_render_reload:

        Experimental options. Disabled by default.<br/><br/>

        If True, will attempt to only execute the logic in render() that is required to calculate your
        `reload` parameters. Other logic will be short-circuited. If your render function has significant computation for other
        properties this can be a significant performance improvement. However, it is experimental and may not work in all cases.

    :type experimental_render_reload: bool

    :return: The response model to use for this endpoint. If a BaseModel is not provided (you pass
        a dictionary or a SQLModel object ofr instance), we will try to convert the response object
        into the proper JSON response based on your typehint.
    :rtype: BaseModel | None | fastapi.JSONResponse

    """

    def decorator_with_args(
        reload: tuple[FieldClassDefinition, ...] | None = None,
        response_model: Type[BaseModel] | None = None,
        exception_models: list[Type[APIException]] | None = None,
        experimental_render_reload: bool = False,
    ):
        def wrapper(func: Callable):
            passthrough_model, response_type = extract_response_model_from_signature(
                func, response_model
            )

            if response_type == ResponseModelType.ITERATOR_RESPONSE:
                raise ValueError(
                    "Sideeffect functions cannot return an iterator response. Use a normal response model instead."
                )

            original_sig = signature(func)
            function_needs_request = "request" in original_sig.parameters

            # Must be delayed until we actually have a self reference
            # Keep a dictionary versus a single value, so we are able to support one
            # controller definition (and therefore a single @sideeffect decorator) being
            # subclassed multiple times
            render_fns: dict[Any, Callable] = {}

            @wraps(func)
            async def inner(self: "ControllerBase", *func_args, **func_kwargs):
                # Delay
                nonlocal render_fns
                render_fn = render_fns.get(self)
                if not render_fn:
                    if experimental_render_reload and reload:
                        render_fn = partial(
                            crop_function_for_return_keys(
                                self.render, keys=[field.key for field in reload]
                            ),
                            self,
                        )
                    else:
                        render_fn = self.render
                    render_fns[self] = render_fn

                # This shouldn't occur - but is necessary for typehinting
                if not render_fn:
                    raise ValueError(
                        "Unable to compute a valid render function for sideeffect"
                    )

                # Check if the original function expects a 'request' parameter
                request = func_kwargs.pop("request")
                if not request:
                    raise ValueError(
                        "Sideeffect function must have a 'request' parameter"
                    )

                if function_needs_request:
                    func_kwargs["request"] = request

                passthrough_values = func(self, *func_args, **func_kwargs)

                # If the original function is async, we now have an awaitable task
                if isawaitable(passthrough_values):
                    passthrough_values = await passthrough_values

                # We need to get the original function signature, and then call it with the request
                async with get_render_parameters(self, request) as values:
                    # Some render functions rely on the URL of the page to make different logic
                    # For this we rely on the Referrer header that is sent on the fetch(). Note that this
                    # referrer can be spoofed, so it assumes that the endpoint also internally validates
                    # the caller has correct permissions to access the data.
                    server_data = render_fn(**values)
                    if isawaitable(server_data):
                        server_data = await server_data

                    # Following types ignored to support 3.10
                    final_payload: SideeffectResponseBase[Any] = {  # type: ignore
                        "sideeffect": server_data,
                        "passthrough": passthrough_values,
                    }
                    return format_final_action_response(final_payload)  # type: ignore

            # Update the signature of 'inner' to include 'request: Request'
            # We need to modify this to conform to the request parameters that are sniffed
            # when the component is mounted
            # https://github.com/tiangolo/fastapi/blob/a235d93002b925b0d2d7aa650b7ab6d7bb4b24dd/fastapi/dependencies/utils.py#L250
            sig = signature(inner)
            parameters = list(sig.parameters.values())
            if "request" not in sig.parameters:
                request_param = Parameter(
                    "request", Parameter.POSITIONAL_OR_KEYWORD, annotation=Request
                )
                parameters.insert(1, request_param)  # Insert after 'self'
            new_sig = sig.replace(parameters=parameters)
            inner.__wrapped__.__signature__ = new_sig  # type: ignore

            metadata = init_function_metadata(inner, FunctionActionType.SIDEEFFECT)
            metadata.reload_states = reload
            metadata.passthrough_model = passthrough_model
            metadata.exception_models = exception_models
            metadata.media_type = None  # Use the default json response type

            inner.original = create_original_fn(func)  # type: ignore
            return inner

        return wrapper

    if args and callable(args[0]):
        # It's used as @sideeffect without arguments
        func = args[0]
        return decorator_with_args()(func)
    else:
        # It's used as @sideeffect(xyz=2) with arguments
        return decorator_with_args(**kwargs)


@asynccontextmanager
async def get_render_parameters(
    controller: "ControllerBase",
    request: Request,
):
    """
    render() components are allowed to have all of the same dependency injections
    that a normal endpoint does. This function parses the render function signature in
    the same way that FastAPI/Starlette do, so we're able to pretend as if a new request
    is coming into the view endpoint.

    NOTE: We exclude calls to background tasks, since these are rarely intended for
    automatic calls to the rendering due to side-effects.

    """
    # Create a synthetic request object that we would use to access the core
    # html. This will be passed through the dependency resolution pipeline so to
    # render() it's indistinguishable from a real request and therefore will render
    # in the same way.
    # The referrer should capture the page that they're actually on
    referer = request.headers.get("referer")
    parsed_path = urlparse(referer or controller.url)
    view_request = Request(
        {
            "type": request.scope["type"],
            "path": parsed_path.path,
            "query_string": parsed_path.query,
            "headers": request.headers.raw,
            "http_version": request.scope["http_version"],
            "method": "GET",
            "scheme": request.scope["scheme"],
            "client": request.scope["client"],
            "server": request.scope["server"],
        }
    )

    if not controller.definition:
        raise RuntimeError(
            "Controller definition is not set. This might indicate you're calling a"
            " sideeffect from outside of an AppController context."
        )

    # Follow starlette's original logic to resolve routes, since this provides us the necessary
    # metadata about URL paths. Unlike in the general-purpose URL resolution case, however,
    # we already know which route should be resolved so we can shortcut having to
    # match non-relevant paths.
    # https://github.com/encode/starlette/blob/5c43dde0ec0917673bb280bcd7ab0c37b78061b7/starlette/routing.py#L544
    for route in (
        controller.definition.render_router.routes
        if controller.definition.render_router is not None
        else []
    ):
        match, child_scope = route.matches(view_request.scope)
        if match != Match.FULL:
            raise RuntimeError(
                f"Route {route} did not match ({match}) {view_request.scope}"
            )
        view_request.scope = {
            # Make sure we're populating the path params with some values
            # even if they're not extracted in either the view or the child definition
            "path_params": {},
            **view_request.scope,
            **child_scope,
        }

    try:
        async with get_function_dependencies(
            callable=controller.render,
            url=(
                controller.url
                if not isinstance(controller, LayoutControllerBase)
                else None
            ),
            request=(
                view_request
                if not isinstance(controller, LayoutControllerBase)
                else None
            ),
        ) as values:
            yield values
    except RuntimeError as e:
        raise RuntimeError(
            f"Error occurred while resolving dependencies for render(): {controller}: {e}"
        ) from e
