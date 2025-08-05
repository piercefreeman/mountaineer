"""
Handle different response types (standard, SSE, etc.) with their requirements
for dependency injection and request handling.

"""

from abc import ABC, abstractmethod
from functools import wraps
from inspect import Parameter, Signature, isawaitable, signature
from json import dumps as json_dumps
from typing import TYPE_CHECKING, Any, Callable

from fastapi import Request, params as fastapi_params
from fastapi.responses import StreamingResponse

from mountaineer.actions.fields import (
    FunctionMetadata,
    ResponseModelType,
    SideeffectResponseBase,
    format_final_action_response,
)
from mountaineer.constants import STREAM_EVENT_TYPE
from mountaineer.dependencies import (
    get_function_dependencies,
    isolate_dependency_only_function,
)

if TYPE_CHECKING:
    from typing import AsyncIterator

    from pydantic import BaseModel

    from mountaineer.controller import ControllerBase


def wrap_passthrough_generator(generator: "AsyncIterator[BaseModel]"):
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


class ResponseStrategy(ABC):
    """Base class for response handling strategies."""

    @abstractmethod
    def should_handle(self, metadata: FunctionMetadata) -> bool:
        """Determine if this strategy should handle the given endpoint."""
        pass

    @abstractmethod
    def create_wrapper(
        self,
        func: Callable,
        metadata: FunctionMetadata,
        response_type: ResponseModelType,
        raw_response: bool = False,
    ) -> Callable:
        """Create the appropriate wrapper for the endpoint."""
        pass

    @abstractmethod
    def prepare_for_mounting(
        self,
        controller: "ControllerBase",
        fn: Callable,
        metadata: FunctionMetadata,
    ) -> Callable:
        """Prepare the endpoint for mounting to the FastAPI router."""
        pass

    def has_dependencies(self, func: Callable) -> bool:
        """Check if the function has any Depends parameters."""
        sig = signature(func)
        return any(
            isinstance(param.default, fastapi_params.Depends)
            for param in sig.parameters.values()
        )


class StandardResponseStrategy(ResponseStrategy):
    """Strategy for standard (non-streaming) responses."""

    def should_handle(self, metadata: FunctionMetadata) -> bool:
        return metadata.media_type != STREAM_EVENT_TYPE

    def create_wrapper(
        self,
        func: Callable,
        metadata: FunctionMetadata,
        response_type: ResponseModelType,
        raw_response: bool = False,
    ) -> Callable:
        """Create standard wrapper that handles responses normally."""

        @wraps(func)
        async def inner(self: "ControllerBase", *func_args, **func_kwargs):
            response = func(self, *func_args, **func_kwargs)
            if isawaitable(response):
                response = await response

            if raw_response:
                return response

            # Following types ignored to support 3.10
            final_payload: SideeffectResponseBase[Any] = {  # type: ignore
                "passthrough": response,
            }
            return format_final_action_response(final_payload)  # type: ignore

        return inner

    def prepare_for_mounting(
        self,
        controller: "ControllerBase",
        fn: Callable,
        metadata: FunctionMetadata,
    ) -> Callable:
        """Standard endpoints are mounted as-is."""
        return fn


class SSEResponseStrategy(ResponseStrategy):
    """Strategy for Server-Sent Events (streaming) responses."""

    def should_handle(self, metadata: FunctionMetadata) -> bool:
        return metadata.media_type == STREAM_EVENT_TYPE

    def create_wrapper(
        self,
        func: Callable,
        metadata: FunctionMetadata,
        response_type: ResponseModelType,
        raw_response: bool = False,
    ) -> Callable:
        """Create wrapper that delays dependency injection for SSE."""

        if self.has_dependencies(func):
            # Create a wrapper that handles dependency injection inside the generator
            @wraps(func)
            async def inner(
                self: "ControllerBase", request: Request, *func_args, **func_kwargs
            ):
                if raw_response:
                    # For raw responses, we still need to handle dependencies
                    dep_only_func = isolate_dependency_only_function(func)
                    async with get_function_dependencies(
                        callable=dep_only_func,
                        request=request,
                    ) as dep_values:
                        merged_kwargs = {**func_kwargs, **dep_values}
                        response = func(self, *func_args, **merged_kwargs)
                        if isawaitable(response):
                            response = await response
                        return response

                # For SSE, create a generator that manages dependencies
                async def delayed_generator():
                    # Get a function with only dependency parameters for resolution
                    dep_only_func = isolate_dependency_only_function(func)
                    async with get_function_dependencies(
                        callable=dep_only_func,
                        request=request,
                    ) as dep_values:
                        merged_kwargs = {**func_kwargs, **dep_values}
                        generator = func(self, *func_args, **merged_kwargs)
                        if isawaitable(generator):
                            generator = await generator
                        async for value in generator:
                            json_payload = value.model_dump(mode="json")
                            data = json_dumps(dict(passthrough=json_payload))
                            yield f"data: {data}\n"

                return StreamingResponse(
                    delayed_generator(), media_type=STREAM_EVENT_TYPE
                )
        else:
            # No dependencies, use simpler wrapper
            @wraps(func)
            async def inner(self: "ControllerBase", *func_args, **func_kwargs):
                response = func(self, *func_args, **func_kwargs)
                if isawaitable(response):
                    response = await response

                if raw_response:
                    return response

                return wrap_passthrough_generator(response)

        return inner

    def prepare_for_mounting(
        self,
        controller: "ControllerBase",
        fn: Callable,
        metadata: FunctionMetadata,
    ) -> Callable:
        """Prepare SSE endpoint for mounting with special handling for dependencies."""
        if not self.has_dependencies(fn):
            # No dependencies, mount as-is
            return fn

        # Create a wrapper that handles JSON body parsing and excludes dependencies
        controller_ref = controller
        fn_ref = fn

        @wraps(fn)
        async def sse_wrapper(request: Request, **kwargs):
            # Parse JSON body for parameters
            body = {}
            if request.headers.get("content-type") == "application/json":
                try:
                    body = await request.json()
                except Exception:
                    pass

            # Merge body parameters with kwargs
            merged_kwargs = {**body, **kwargs}

            # Call the original method with self (controller) and the request
            return await fn_ref.__func__(  # type: ignore
                controller_ref, request=request, **merged_kwargs
            )

        # Create new signature without Depends parameters
        sig = signature(fn)
        new_params = []
        request_param = None
        other_params = []

        for param in sig.parameters.values():
            if param.name == "self":
                # Skip self for the wrapper since we handle it internally
                continue
            elif param.name == "request":
                request_param = param
            elif not isinstance(param.default, fastapi_params.Depends):
                other_params.append(param)

        # Ensure request parameter exists
        if request_param is None:
            request_param = Parameter(
                "request", Parameter.POSITIONAL_OR_KEYWORD, annotation=Request
            )

        # Build new parameter list without self
        new_params = [request_param] + other_params

        # Update the wrapper's signature
        sse_wrapper.__signature__ = Signature(  # type: ignore
            parameters=new_params, return_annotation=sig.return_annotation
        )

        return sse_wrapper


class ResponseStrategyRegistry:
    """Registry for response strategies."""

    def __init__(self):
        self.strategies = [
            SSEResponseStrategy(),
            StandardResponseStrategy(),  # Default fallback
        ]

    def get_strategy(self, metadata: FunctionMetadata) -> ResponseStrategy:
        """Get the appropriate strategy for the given metadata."""
        for strategy in self.strategies:
            if strategy.should_handle(metadata):
                return strategy
        # Return default strategy if no match
        return self.strategies[-1]


# Global registry instance
response_strategy_registry = ResponseStrategyRegistry()
