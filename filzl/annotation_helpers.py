from dataclasses import is_dataclass, fields
from inspect import isclass
from pydantic import BaseModel, create_model
from pydantic.fields import FieldInfo
from typing import (
    Any,
    Type,
    get_args,
    get_origin,
    Union,
)
from copy import deepcopy
from pydantic._internal._typing_extra import eval_type_lenient
from types import UnionType


def get_value_by_alias(model: BaseModel | dict[str, Any], alias: str):
    """
    Get the value of a pydantic model by its original JSON key. This will look for both the cast
    name and the original name.

    If there's a tie, the cast name will win.

    """
    if isinstance(model, dict):
        # Dictionaries can't have aliases
        return model[alias]

    try:
        return getattr(model, alias)
    except AttributeError:
        # Only run the following if we're not able to find the cast name since in involves
        # an O(n) operation
        for field_name, field in model.model_fields.items():
            if field.alias == alias:
                return getattr(model, field_name)
    raise AttributeError(
        f"No key `{alias}` found in model, either alias or cast value."
    )


def resolve_forwardrefs(
    current_type: type,
    *,
    _globals: dict[str, Any] | None = None,
    _locals: dict[str, Any] | None = None,
):
    """
    Resolves forwardrefs to their true value. Unlike the standard eval_type_lenient logic this also
    supports nested forwardrefs like those found in origin/arg pairs.

    """
    origin = get_origin(current_type)
    args = get_args(current_type)

    if origin:
        origin = resolve_forwardrefs(origin, _globals=_globals, _locals=_locals)
        args = tuple(
            [
                resolve_forwardrefs(arg, _globals=_globals, _locals=_locals)
                for arg in args
            ]
        )

        # Workaround for UnionType not allowing programatic construction
        if origin == UnionType:
            return Union[*args]  # type: ignore

        return origin[*args]

    return eval_type_lenient(current_type, _globals or globals(), _locals or locals())


def yield_all_subtypes(
    model: type,
    _globals: dict[str, Any] | None = None,
    _locals: dict[str, Any] | None = None,
):
    """
    Given a model declaration, yield all of its subtypes. This is useful to determine whether
    a nested model might include a given subtype.

    We support:
        - Pydantic models
        - Dataclasses
        - Origin/Argument typevars, like `list[str]` or `Union[str, int]`
    """

    # Track the models we've already validated to avoid circular dependencies
    already_validated: set[Type[BaseModel]] = set()

    def resolve_types(current_type: type):
        nonlocal already_validated

        # Always echo back the current type to make sure that everything that we've processed
        # is included in the final list
        yield resolve_forwardrefs(current_type, _globals=_globals, _locals=_locals)

        if isclass(current_type) and issubclass(current_type, BaseModel):
            if current_type in already_validated:
                # Avoid circular dependencies
                # If we've already checked this class, we know it's valid
                return

            # Avoid recursion before we short-circuit any future validations to this same model
            already_validated.add(current_type)

            for field_name, field in current_type.model_fields.items():
                # Always field the full annotation, including ones with origins/args
                if field.annotation:
                    yield from resolve_types(field.annotation)

                # In the case of generics, we also want to iterate over the subvalues
                origin = get_origin(field.annotation)
                args = get_args(field.annotation)
                if origin:
                    yield from resolve_types(origin)
                    for arg in args:
                        yield from resolve_types(arg)

        elif is_dataclass(current_type):
            for dataclass_definition in fields(current_type):
                yield from resolve_types(dataclass_definition.type)

    yield from resolve_types(model)


def make_optional_model(model: Type[BaseModel]):
    """
    Given a standard Pydantic model, make all fields optional. Names the new model `{Model}Optional`.

    """
    optional_fields: dict[str, tuple[type, FieldInfo]] = {}

    for field_name, field_definition in model.model_fields.items():
        # We are making modifications to the field definition and don't want a shared memory
        # copy to affect other locations where the original model is used. It _probably_ wouldn't
        # do this anyway since the model has already been instantiated, but this is a good
        # practice to follow.
        new_field_definition = deepcopy(field_definition)

        # The default value is what actaully sets the field to optional within OpenAPI
        # Actually modifying the type to be Optional[T] will just inject a `null` type into
        # an anyOf spec.
        new_field_definition.default = None
        optional_fields[field_name] = (
            field_definition.annotation,
            new_field_definition,
        )

    return create_model(
        f"{model.__name__}Optional",
        **optional_fields,  # type: ignore
    )
