from types import NoneType, UnionType
from typing import Any, Optional, TypeVar, Union, get_args, get_origin


def get_typevar_mapping(cls):
    """
    Get the raw typevar mappings {typvar: generic values} for each
    typevar in the class hierarchy of `cls`.

    """
    mapping: dict[Any, Any] = {}

    # Traverse MRO in reverse order, except `object`
    for base in reversed(cls.__mro__[:-1]):
        # Skip non-generic classes
        if not hasattr(base, "__orig_bases__"):
            continue

        for origin_base in base.__orig_bases__:
            origin = get_origin(origin_base)
            if origin:
                base_params = getattr(origin, "__parameters__", [])
                instantiated_params = get_args(origin_base)

                # Update mapping with current base's mappings
                base_mapping = dict(zip(base_params, instantiated_params))
                for key, value in base_mapping.items():
                    # If value is another TypeVar, resolve it if possible
                    if isinstance(value, TypeVar) and value in mapping:
                        mapping[key] = mapping[value]
                    else:
                        mapping[key] = value

    # Exclude TypeVars from the final mapping
    return mapping


def expand_typevars(raw_values):
    """
    Expand all typevars in the class hierarchy of `cls` to their
    final values. This resolves cases where a typevar in an ancestor
    is resolved by a child value.

    """
    final_values: dict[Any, Any] = {}

    for key, value in raw_values.items():
        # Resolve until we can't resolve anymore
        while isinstance(value, TypeVar) and value in raw_values:
            value = raw_values[value]

        final_values[key] = value

    return final_values


def resolve_generic_type(field_type: Any, type_mapping: dict[TypeVar, Any]) -> Any:
    """
    Recursively resolve generic types, handling Lists, Optionals, and nested generics.

    """
    # If field type is a generic parameter, resolve it directly
    if isinstance(field_type, TypeVar):
        return type_mapping.get(field_type, Any)

    # Handle nested generic types
    origin_type = get_origin(field_type)
    if origin_type is None:
        return field_type

    # Get the type arguments
    type_args = get_args(field_type)

    # Handle Optional types (Union[T, None])
    if origin_type in (Union, UnionType):
        # Check if this is an Optional type (Union with NoneType)
        if NoneType in type_args or type(None) in type_args:
            # Resolve the non-None type argument
            non_none_args = [
                arg for arg in type_args if arg not in (NoneType, type(None))
            ]
            if len(non_none_args) == 1:
                resolved_type = resolve_generic_type(non_none_args[0], type_mapping)
                return Optional[resolved_type]

        # Handle regular Union types
        resolved_args = tuple(
            resolve_generic_type(arg, type_mapping) for arg in type_args
        )
        return Union[resolved_args]

    # Handle other generic types (List, Dict, Set, etc.)
    resolved_args = tuple(resolve_generic_type(arg, type_mapping) for arg in type_args)
    return origin_type[resolved_args] if resolved_args else origin_type
