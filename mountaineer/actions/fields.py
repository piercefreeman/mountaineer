import collections
import collections.abc
import sys
import typing
import warnings
from asyncio import iscoroutinefunction
from enum import Enum
from inspect import (
    isclass,
    ismethod,
)
from json import loads as json_loads
from typing import (
    TYPE_CHECKING,
    Any,
    Awaitable,
    Callable,
    Concatenate,
    Generic,
    Optional,
    ParamSpec,
    Protocol,
    Type,
    TypedDict,
    TypeVar,
    get_args,
    get_origin,
)

import starlette.responses
from fastapi.responses import JSONResponse
from inflection import camelize
from pydantic import BaseModel, create_model
from pydantic.fields import FieldInfo

from mountaineer.annotation_helpers import MountaineerUnsetValue
from mountaineer.exceptions import APIException
from mountaineer.render import FieldClassDefinition, Metadata, RenderBase, RenderNull

if sys.version_info >= (3, 11):
    from typing import NotRequired
else:
    from typing_extensions import NotRequired

if TYPE_CHECKING:
    from mountaineer.controller import ControllerBase


class FunctionActionType(Enum):
    RENDER = "render"
    SIDEEFFECT = "sideeffect"
    PASSTHROUGH = "passthrough"


class ResponseModelType(Enum):
    SINGLE_RESPONSE = "SINGLE_RESPONSE"
    ITERATOR_RESPONSE = "ITERATOR_RESPONSE"


P = TypeVar("P")

if sys.version_info >= (3, 11):

    class SideeffectResponseBase(TypedDict, Generic[P]):
        passthrough: P
        # We can't yet typehint across the boundary of the sideeffect -> render
        # within one class since @sideeffect is isolated to just the wrapped function
        sideeffect: NotRequired[Any]
else:
    # Inheriting from both TypedDict and Generic[P] is not supported in Python 3.10 and below
    class SideeffectResponseBase(dict, Generic[P]):
        pass


T = ParamSpec("T")
R = TypeVar("R")
C = TypeVar("C", covariant=True)


class SideeffectWrappedCallable(Protocol[C, T, R]):
    def __call__(
        self: Any, *args: T.args, **kwargs: T.kwargs
    ) -> Awaitable[SideeffectResponseBase[R]]:
        ...

    # Since the original function is extracted directly from the class, it's
    # just a hanging function and no longer an instance method. Users therefore
    # need to call it with the class instance explicitly as the first argument.
    original: Callable[Concatenate[C, T], Awaitable[R]]


class SideeffectRawCallable(Protocol[C, T, R]):
    def __call__(self: Any, *args: T.args, **kwargs: T.kwargs) -> Awaitable[R]:
        ...

    original: Callable[Concatenate[C, T], Awaitable[R]]


class FunctionMetadata(BaseModel):
    function_name: str
    action_type: FunctionActionType

    # Specified for sideeffects, where all data shouldn't be update. Limits the
    # update to fields defined in this tuple.
    reload_states: tuple[
        FieldClassDefinition, ...
    ] | None | MountaineerUnsetValue = MountaineerUnsetValue()

    # Defines the data schema returned from the function that will be included in the
    # response payload sent to the client. This might be used for either passthrough
    # or sideeffect
    passthrough_model: Type[
        BaseModel
    ] | None | MountaineerUnsetValue = MountaineerUnsetValue()
    exception_models: list[
        Type[APIException]
    ] | None | MountaineerUnsetValue = MountaineerUnsetValue()
    media_type: str | None | MountaineerUnsetValue = MountaineerUnsetValue()
    is_raw_response: bool = False

    # Render type, defines the data model that is returned by the render typehint
    # If "None", the user has explicitly stated that no render model is returned
    render_model: Type[
        RenderBase
    ] | None | MountaineerUnsetValue = MountaineerUnsetValue()

    # Inserted by the render decorator
    return_model: Type[BaseModel] | MountaineerUnsetValue = MountaineerUnsetValue()

    model_config = {
        "arbitrary_types_allowed": True,
    }

    #
    # Accessors for polymorphic variables
    # These convenience methods are used to ensure client callers that this function metadata
    # does have the expected values. They should only be used in cases that you know based on runtime
    # guarantees that certain functions will have certain attributes.
    #
    def get_reload_states(self) -> tuple[FieldClassDefinition, ...] | None:
        if isinstance(self.reload_states, MountaineerUnsetValue):
            raise ValueError("Reload states not set")
        return self.reload_states

    def get_render_model(self) -> Type[RenderBase] | None:
        if isinstance(self.render_model, MountaineerUnsetValue):
            raise ValueError("Render model not set")
        return self.render_model or RenderNull

    def get_passthrough_model(self) -> Type[BaseModel] | None:
        if isinstance(self.passthrough_model, MountaineerUnsetValue):
            raise ValueError("Passthrough model not set")
        return self.passthrough_model

    def get_exception_models(self) -> list[Type[APIException]] | None:
        if isinstance(self.exception_models, MountaineerUnsetValue):
            raise ValueError("Exception models not set")
        return self.exception_models

    def get_media_type(self) -> str | None:
        if isinstance(self.media_type, MountaineerUnsetValue):
            raise ValueError("Media type not set")
        return self.media_type

    def get_is_raw_response(self) -> bool:
        return self.is_raw_response

    def get_return_model(self) -> Type[BaseModel]:
        if isinstance(self.return_model, MountaineerUnsetValue):
            raise ValueError("Return model not set")
        return self.return_model


METADATA_ATTRIBUTE = "_mountaineer_metadata"


def init_function_metadata(fn: Callable, action_type: FunctionActionType):
    if ismethod(fn):
        fn = fn.__func__  # type: ignore

    function_name = fn.__name__
    metadata = FunctionMetadata(function_name=function_name, action_type=action_type)
    setattr(fn, METADATA_ATTRIBUTE, metadata)
    return metadata


def get_function_metadata(fn: Callable) -> FunctionMetadata:
    if ismethod(fn):
        fn = fn.__func__  # type: ignore

    if not hasattr(fn, METADATA_ATTRIBUTE):
        raise AttributeError(f"Function {fn.__name__} does not have metadata")

    metadata = getattr(fn, METADATA_ATTRIBUTE)

    if not isinstance(metadata, FunctionMetadata):
        raise AttributeError(f"Function {fn.__name__} has invalid metadata")

    return metadata


def annotation_is_metadata(annotation: type | None):
    if not annotation:
        return

    return annotation == Metadata or annotation == Optional[Metadata]


def fuse_metadata_to_response_typehint(
    metadata: FunctionMetadata,
    controller: "ControllerBase",
    render_model: Type[RenderBase] | None,
) -> Type[BaseModel]:
    """
    Functions can either be marked up with side effects, explicit responses, or both.
    This function merges them into the expected output payload so we can typehint the responses.
    """
    passthrough_fields = {}
    sideeffect_fields = {}

    if metadata.passthrough_model is not None and not isinstance(
        metadata.passthrough_model, MountaineerUnsetValue
    ):
        passthrough_fields = {**metadata.passthrough_model.model_fields}

    if metadata.action_type == FunctionActionType.SIDEEFFECT and render_model:
        # By default, reload all fields
        sideeffect_fields = {**render_model.model_fields}

        # Ignore the metadata since this shouldn't be passed during sideeffects
        sideeffect_fields = {
            field_name: field_definition
            for field_name, field_definition in sideeffect_fields.items()
            if not annotation_is_metadata(field_definition.annotation)
        }

        if metadata.reload_states is not None and not isinstance(
            metadata.reload_states, MountaineerUnsetValue
        ):
            # Make sure this class actually aligns to the response model
            # If not the user mis-specified the reload states
            #
            # We allow the reload state to be a subclass of the render model, in case the method
            # was originally defined in the superclass. This will result in us sending a subset
            # of the child controller's fields - but since our differential update is based on the
            # original state and modified, this will resolve correctly for the client
            reload_classes = {field.root_model for field in metadata.reload_states}
            reload_keys = {field.key for field in metadata.reload_states}
            if len(reload_classes) != 1 or not issubclass(
                render_model, next(iter(reload_classes))
            ):
                raise ValueError(
                    f"Reload states {reload_classes} do not align to response model {render_model}"
                )
            sideeffect_fields = {
                field_name: field_definition
                for field_name, field_definition in render_model.model_fields.items()
                if field_name in reload_keys
            }

    base_response_name = camelize(metadata.function_name) + "Response"
    base_response_params = {}

    if passthrough_fields:
        base_response_params["passthrough"] = (
            create_model(
                base_response_name + "Passthrough",
                **{
                    field_name: (field_definition.annotation, field_definition)  # type: ignore
                    for field_name, field_definition in passthrough_fields.items()
                },
            ),
            FieldInfo(alias="passthrough"),
        )

    if sideeffect_fields:
        base_response_params["sideeffect"] = (
            create_model(
                base_response_name + "SideEffect",
                **{
                    field_name: (field_definition.annotation, field_definition)  # type: ignore
                    for field_name, field_definition in sideeffect_fields.items()
                },
            ),
            FieldInfo(alias="sideeffect"),
        )

    model: Type[BaseModel] = create_model(
        base_response_name,
        **base_response_params,  # type: ignore
    )

    return model


def format_final_action_response(dict_payload: dict[str, Any]):
    """
    Wrapper to allow actions to respond with an explicit JSONResponse, or a dictionary. This lets
    both sideeffects and passthrough payloads to inject header metadata that otherwise can't be captured
    in a regular BaseModel.

    Since the eventual result of an action is a combined sideeffect+passthrough payload, we need to
    merge the final payload into the explicit response.

    """
    responses: list[tuple[str, JSONResponse]] = [
        (key, response)
        for key, response in dict_payload.items()
        if isinstance(response, JSONResponse)
    ]

    if len(responses) > 1:
        raise ValueError(f"Multiple conflicting responses returned: {responses}")

    if len(responses) == 0:
        return dict_payload

    response_key, response = responses[0]
    dict_payload[response_key] = json_loads(response.body)

    # Now inject the newly formatted response into the response object
    return JSONResponse(
        content=dict_payload,
        status_code=response.status_code,
        headers={
            key: value
            for key, value in response.headers.items()
            if key not in {"content-length", "content-type"}
        },
    )


def extract_response_model_from_signature(
    func: Callable, explicit_response: Type[BaseModel] | None = None
):
    typehinted_response = func.__annotations__.get("return", MountaineerUnsetValue())
    if explicit_response:
        warnings.warn(
            (
                "The response_model argument is deprecated. Instead, just typehint your function explicitly:\n"
                "def my_function() -> MyResponseModel:"
            ),
            DeprecationWarning,
            stacklevel=2,
        )

    if explicit_response:
        return explicit_response, ResponseModelType.SINGLE_RESPONSE

    if isinstance(typehinted_response, MountaineerUnsetValue):
        # This will be converted into a ValueError in the future
        # For now, backwards compatible with the old markup
        warnings.warn(
            (
                f"You must typehint the return value of your `{func}` with either a BaseModel or None.\n"
                "We will stop inferring `None` as a response model in the future."
            ),
            DeprecationWarning,
            stacklevel=2,
        )
        return None, ResponseModelType.SINGLE_RESPONSE

    return extract_model_from_decorated_types(typehinted_response)


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
        typing.Iterator,
        typing.AsyncIterator,
        # At runtime our types are sometimes instantiated as collections.abc objects
        collections.abc.Iterator,
        collections.abc.AsyncIterator,
    ):
        args = get_args(type_hint)
        if args and issubclass(args[0], BaseModel):
            return args[0], ResponseModelType.ITERATOR_RESPONSE
        raise ValueError(
            f"Invalid response_model typehint for iterator action: {type_hint} {origin_type} {args}"
        )
    elif isclass(type_hint) and issubclass(type_hint, starlette.responses.Response):
        # No pydantic model to include in the API schema, instead the endpoint
        # will just return the raw value
        return None, ResponseModelType.SINGLE_RESPONSE

    raise ValueError(
        f"Invalid response_model typehint for standard action: {type_hint}"
    )


def create_original_fn(fn):
    """
    To fulfill our typehints for "original" that are returned from @sideeffect
    and @passthrough we have to make them all async even if they weren't originally.

    """
    if iscoroutinefunction(fn):
        return fn
    else:

        async def async_fn(*args, **kwargs):
            return fn(*args, **kwargs)

        return async_fn
