from dataclasses import fields, is_dataclass
from inspect import isclass
from types import UnionType
from typing import (
    Any,
    Type,
    Union,
    get_args,
    get_origin,
)

from pydantic import BaseModel
from pydantic._internal._typing_extra import eval_type_lenient


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
    current_type: type | str,
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
            return Union[tuple(args)]  # type: ignore

        return origin[tuple(args)]

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

    def resolve_types(current_type: type | str):
        nonlocal already_validated

        # Always echo back the current type to make sure that everything that we've processed
        # is included in the final list
        yield resolve_forwardrefs(current_type, _globals=_globals, _locals=_locals)

        # If we have nested types, we want to resolve those as well
        origin = get_origin(current_type)
        args = get_args(current_type)
        if origin:
            yield from resolve_types(origin)
            for arg in args:
                yield from resolve_types(arg)
            return

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


class MountaineerUnsetValue:
    """
    A sentinel value to indicate that a value has not been set. This is useful for cases where
    we need to separate explicit Nones from missing values.
    """

    pass
