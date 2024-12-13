from typing import Any, TypeVar, get_args, get_origin


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
