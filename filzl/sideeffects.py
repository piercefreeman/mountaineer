from inspect import ismethod
from filzl.render import FieldClassDefinition, RenderBase
from typing import Callable, Type, Any
from functools import wraps
from pydantic import BaseModel, create_model
from pydantic.fields import FieldInfo
from enum import Enum
from inflection import camelize
from typing import overload


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
                for field_name, field_definition in render_model.model_fields.items()
                if field_name in reload_keys
            }

    print("RETURN FIELDS", passthrough_fields, sideeffect_fields)

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


@overload
def sideeffect(
    # We need to typehint reload to be Any, because during typechecking our Model.attribute will just
    # yield whatever the typehint of that field is. Only at runtime does it become a FieldClassDefinition
    reload: tuple[Any, ...] | None = None,
    response_model: Type[BaseModel] | None = None,
) -> Callable[[Callable], Callable]:
    ...


@overload
def sideeffect(func: Callable) -> Callable:
    ...


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
        def wrapper(func: Callable):
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


@overload
def passthrough(
    response_model: Type[BaseModel] | None = None,
) -> Callable[[Callable], Callable]:
    ...


@overload
def passthrough(func: Callable) -> Callable:
    ...


def passthrough(*args, **kwargs):
    """
    By default, we mask out function return values to avoid leaking any unintended data to client applications. This
    decorator marks a function .

    :response_model: Like in FastAPI, the response model to use for this endpoint. If not provided, will
        try to convert the response object into the proper JSON response as-is.

    """

    def decorator_with_args(response_model: Type[BaseModel] | None):
        def wrapper(func: Callable):
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
