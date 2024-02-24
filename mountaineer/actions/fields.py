from enum import Enum
from inspect import ismethod
from json import loads as json_loads
from typing import Any, Callable, Optional, Type

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from inflection import camelize
from pydantic import BaseModel, create_model
from pydantic.fields import FieldInfo

from mountaineer.annotation_helpers import MountaineerUnsetValue
from mountaineer.exceptions import APIException
from mountaineer.render import FieldClassDefinition, Metadata, RenderBase, RenderNull


class FunctionActionType(Enum):
    RENDER = "render"
    SIDEEFFECT = "sideeffect"
    PASSTHROUGH = "passthrough"


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

    # Render type, defines the data model that is returned by the render typehint
    # If "None", the user has explicitly stated that no render model is returned
    render_model: Type[RenderBase] | MountaineerUnsetValue = MountaineerUnsetValue()

    # Inserted by the render decorator
    url: str | MountaineerUnsetValue = MountaineerUnsetValue()
    return_model: Type[BaseModel] | MountaineerUnsetValue = MountaineerUnsetValue()
    render_router: APIRouter | MountaineerUnsetValue = MountaineerUnsetValue()

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

    def get_render_model(self) -> Type[RenderBase]:
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

    def get_url(self) -> str:
        if isinstance(self.url, MountaineerUnsetValue):
            raise ValueError("URL not set")
        return self.url

    def get_return_model(self) -> Type[BaseModel]:
        if isinstance(self.return_model, MountaineerUnsetValue):
            raise ValueError("Return model not set")
        return self.return_model

    def get_render_router(self) -> APIRouter:
        if isinstance(self.render_router, MountaineerUnsetValue):
            raise ValueError("Render router not set")
        return self.render_router


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
    render_model: Type[RenderBase],
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

    if metadata.action_type == FunctionActionType.SIDEEFFECT:
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
            reload_classes = {field.root_model for field in metadata.reload_states}
            reload_keys = {field.key for field in metadata.reload_states}
            if reload_classes != {render_model}:
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


def handle_explicit_responses(
    dict_payload: dict[str, Any],
):
    """
    Wrapper to allow actions to respond with an explicit Response, or a dictionary. If it returns
    with a Response, we will manipulate the output to validate to our expected output schema.
    """
    responses = [
        (key, response)
        for key, response in dict_payload.items()
        if isinstance(response, JSONResponse)
    ]

    if len(responses) > 1:
        raise ValueError("Multiple conflicting responses returned")

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
