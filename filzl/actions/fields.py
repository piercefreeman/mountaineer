from enum import Enum
from inspect import ismethod
from typing import Callable, Optional, Type

from fastapi import APIRouter
from inflection import camelize
from pydantic import BaseModel, create_model
from pydantic.fields import FieldInfo

from filzl.annotation_helpers import yield_all_subtypes
from filzl.render import FieldClassDefinition, Metadata, RenderBase


class FunctionActionType(Enum):
    RENDER = "render"
    SIDEEFFECT = "sideeffect"
    PASSTHROUGH = "passthrough"


class FunctionMetadata(BaseModel):
    function_name: str
    action_type: FunctionActionType

    # Specified for sideeffects, where all data shouldn't be update. Limits the
    # update to fields defined in this tuple.
    reload_states: tuple[FieldClassDefinition, ...] | None = None

    # Defines the data schema returned from the function that will be included in the
    # response payload sent to the client. This might be used for either passthrough
    # or sideeffect
    passthrough_model: Type[BaseModel] | None = None

    # Render type, defines the data model that is returned by the render typehint
    render_model: Type[RenderBase] | None = None

    # Inserted by the render decorator
    url: str | None = None
    return_model: Type[BaseModel] | None = None
    render_router: APIRouter | None = None

    model_config = {
        "arbitrary_types_allowed": True,
    }

    #
    # Accessors for polymorphic variables
    # These convenience methods are used to ensure client callers that this function metadata
    # does have the expected values. They should only be used in cases that you know based on runtime
    # guarantees that certain functions will have certain attributes.
    #
    def get_reload_states(self) -> tuple[FieldClassDefinition, ...]:
        if not self.reload_states:
            raise ValueError("Reload states not set")
        return self.reload_states

    def get_render_model(self) -> Type[RenderBase]:
        if not self.render_model:
            raise ValueError("Render model not set")
        return self.render_model

    def get_passthrough_model(self) -> Type[BaseModel]:
        if not self.passthrough_model:
            raise ValueError("Passthrough model not set")
        return self.passthrough_model

    def get_url(self) -> str:
        if not self.url:
            raise ValueError("URL not set")
        return self.url

    def get_return_model(self) -> Type[BaseModel]:
        if not self.return_model:
            raise ValueError("Return model not set")
        return self.return_model

    def get_render_router(self) -> APIRouter:
        if not self.render_router:
            raise ValueError("Render router not set")
        return self.render_router


METADATA_ATTRIBUTE = "_filzl_metadata"


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

    all_subtypes = set(yield_all_subtypes(annotation))
    return all_subtypes == {Metadata} or all_subtypes == {Optional[Metadata]}


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

    if metadata.passthrough_model:
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

        if metadata.reload_states:
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
