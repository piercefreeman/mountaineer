from inspect import ismethod
from filzl.render import FieldClassDefinition, RenderBase
from typing import Callable, Type
from types import MethodType
from functools import wraps
from pydantic import BaseModel, create_model
from pydantic.fields import FieldInfo
from enum import Enum
from inflection import camelize
from itertools import chain


class FunctionActionType(Enum):
    RENDER = "render"
    SIDEEFFECT = "sideeffect"
    PASSTHROUGH = "passthrough"


class FunctionMetadata(BaseModel):
    function_name: str
    action_type: FunctionActionType

    # Sideeffect type
    reload_states: tuple[FieldClassDefinition, ...] | None = None

    # Passthrough type
    passthrough_model: Type[BaseModel] | None = None

    # Render type
    render_model: Type[RenderBase] | None = None


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

    print("METADATA", metadata.action_type)

    if metadata.passthrough_model:
        passthrough_fields = {**metadata.passthrough_model.model_fields}

    if metadata.action_type == FunctionActionType.SIDEEFFECT:
        # By default, reload all fields
        sideeffect_fields = {**render_model.model_fields}
        print("SIDE EFFECT", sideeffect_fields)

        if metadata.reload_states:
            print("WILL FILTER", metadata.reload_states)
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
                for field_name, field_definition in render_model.model_fields
                if field_name in reload_keys
            }

    print("RETURN FIELDS", passthrough_fields, sideeffect_fields)

    return create_model(
        camelize(metadata.function_name) + "Response",
        **{
            field_name: (field_definition.annotation, field_definition) # type: ignore
            for field_name, field_definition in chain(passthrough_fields.items(), sideeffect_fields.items())
        },
    )

def sideeffect(*args, **kwargs):
    """
    Mark a function as causing a sideeffect to the data. This will force a reload of the full (or partial) server state
    and sync these changes down to the client page.

    :reload: If provided, will ONLY reload these fields. By default will reload all fields. Otherwise, why
        specify a sideeffect at all?

    """

    def decorator_with_args(
        reload: tuple[FieldClassDefinition, ...] | None = None,
        response_model: Type[BaseModel] | None = None,
    ):
        def wrapper(func: MethodType):
            @wraps(func)
            def inner(self, *func_args, **func_kwargs):
                return func(self, *func_args, **func_kwargs)

            metadata = init_function_metadata(inner, FunctionActionType.SIDEEFFECT)
            metadata.reload_states = reload
            metadata.passthrough_model = response_model
            return inner

        return wrapper

    if args and callable(args[0]):
        # It's used as @sideeffect without arguments
        func = args[0]
        return decorator_with_args()(func)
    else:
        # It's used as @sideeffect(xyz=2) with arguments
        return decorator_with_args(*args, **kwargs)


def passthrough(*args, **kwargs):
    """
    By default, we mask out function return values to avoid leaking any unintended data to client applications. This
    decorator marks a function .

    :response_model: Like in FastAPI, the response model to use for this endpoint. If not provided, will
        try to convert the response object into the proper JSON response as-is.

    """

    def decorator_with_args(response_model: Type[BaseModel] | None):
        def wrapper(func: MethodType):
            @wraps(func)
            def inner(self, *func_args, **func_kwargs):
                return func(self, *func_args, **func_kwargs)

            metadata = init_function_metadata(inner, FunctionActionType.PASSTHROUGH)
            metadata.passthrough_model = response_model
            return inner

        return wrapper

    if args and callable(args[0]):
        # It's used as @sideeffect without arguments
        func = args[0]
        return decorator_with_args(None)(func)
    else:
        # It's used as @sideeffect(xyz=2) with arguments
        return decorator_with_args(*args, **kwargs)
