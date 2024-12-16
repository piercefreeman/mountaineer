from enum import Enum
from typing import Type

from pydantic import BaseModel

from mountaineer.actions.fields import FunctionActionType
from mountaineer.client_builder.parser import (
    ActionWrapper,
    ControllerWrapper,
    EnumWrapper,
    ExceptionWrapper,
    FieldWrapper,
    ModelWrapper,
    WrapperName,
)
from mountaineer.client_builder.types import TypeDefinition
from mountaineer.controller import ControllerBase
from mountaineer.exceptions import APIException


def create_model_wrapper(
    model: Type[BaseModel],
    name: str,
    fields: list[FieldWrapper] | None = None,
    superclasses: list[ModelWrapper] | None = None,
) -> ModelWrapper:
    wrapper_name = WrapperName(name)
    return ModelWrapper(
        name=wrapper_name,
        module_name="test_module",
        model=model,
        isolated_model=model,  # Simplified for testing
        superclasses=superclasses or [],
        value_models=fields or [],
    )


# Helper function to create field wrappers
def create_field_wrapper(
    name: str,
    type_hint: type | ModelWrapper | EnumWrapper | TypeDefinition,
    required: bool = True,
) -> FieldWrapper:
    return FieldWrapper(name=name, value=type_hint, required=required)


# Helper function to create exception wrappers
def create_exception_wrapper(
    exception: Type[APIException],
    name: str,
    status_code: int,
    value_models: list[FieldWrapper] | None = None,
) -> ExceptionWrapper:
    wrapper_name = WrapperName(name)
    return ExceptionWrapper(
        name=wrapper_name,
        module_name="test_module",
        status_code=status_code,
        exception=exception,
        value_models=value_models or [],
    )


def create_action_wrapper(
    name: str,
    params: list[FieldWrapper] | None = None,
    response_model: Type[BaseModel] | None = None,
    request_body: ModelWrapper | None = None,
    action_type: FunctionActionType = FunctionActionType.PASSTHROUGH,
) -> ActionWrapper:
    response_wrapper = (
        create_model_wrapper(response_model, response_model.__name__)
        if response_model
        else None
    )
    return ActionWrapper(
        name=name,
        module_name="test_module",
        action_type=action_type,
        params=params or [],
        headers=[],
        request_body=request_body,
        response_bodies={ControllerBase: response_wrapper} if response_wrapper else {},
        exceptions=[],
        is_raw_response=False,
        is_streaming_response=False,
        controller_to_url={ControllerBase: f"/api/{name}"},
    )


def create_controller_wrapper(
    name: str,
    actions: dict[str, ActionWrapper] | None = None,
    superclasses: list[ControllerWrapper] | None = None,
    entrypoint_url: str | None = None,
) -> ControllerWrapper:
    wrapper_name = WrapperName(name)
    return ControllerWrapper(
        name=wrapper_name,
        module_name="test_module",
        entrypoint_url=entrypoint_url,
        controller=type(name, (ControllerBase,), {}),
        superclasses=superclasses or [],
        queries=[],
        paths=[],
        render=None,
        actions=actions or {},
    )


def create_enum_wrapper(enum_class: Type[Enum]) -> EnumWrapper:
    """Helper function to create enum wrappers"""
    wrapper_name = WrapperName(enum_class.__name__)
    return EnumWrapper(name=wrapper_name, module_name="test_module", enum=enum_class)
