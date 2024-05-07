import types
from inspect import isclass
from typing import Type, Union, get_args, get_origin


def mro_distance(obj_type: Type, target_type: Type) -> float:
    """
    Calculate the MRO distance between obj_type and target_type.
    Returns a large number if no match is found.

    """
    if not isclass(obj_type):
        obj_type = type(obj_type)
    if not isclass(target_type):
        target_type = type(target_type)

    # Compare class types for exact match
    if obj_type == target_type:
        return 0

    # Check if obj_type is a subclass of target_type using the MRO
    try:
        return obj_type.mro().index(target_type)  # type: ignore
    except ValueError:
        return float("inf")


def is_type_compatible(obj_type: Type, target_type: Type) -> float:
    """
    Relatively comprehensive type compatibility checker. This function is
    used to check if a SQLModel type has has a registered object that can
    handle it.

    Specifically returns the MRO distance where 0 indicates
    an exact match, 1 indicates a direct ancestor, and so on. Returns a large number
    if no compatibility is found.

    """
    # If obj_type is a nested type, each of these types must be compatible
    # with the corresponding type in target_type
    if get_origin(obj_type) is Union or isinstance(obj_type, types.UnionType):
        return max(is_type_compatible(t, target_type) for t in get_args(obj_type))

    # Handle OR types
    if get_origin(target_type) is Union or isinstance(target_type, types.UnionType):
        return min(is_type_compatible(obj_type, t) for t in get_args(target_type))

    # Handle Type[Values] like typehints where we want to typehint a class
    if get_origin(target_type) == type:
        return is_type_compatible(obj_type, get_args(target_type)[0])

    # Handle dict[str, str] like typehints
    # We assume that each arg in order must be matched with the target type
    obj_origin = get_origin(obj_type)
    target_origin = get_origin(target_type)
    if obj_origin and target_origin:
        if obj_origin == target_origin:
            return max(
                is_type_compatible(t1, t2)
                for t1, t2 in zip(get_args(obj_type), get_args(target_type))
            )
        else:
            return float("inf")

    # For lists, sets, and tuple objects make sure that each object matches
    # the target type
    if isinstance(obj_type, (list, set, tuple)):
        if type(obj_type) != get_origin(target_type):
            return float("inf")
        return max(
            is_type_compatible(obj, get_args(target_type)[0]) for obj in obj_type
        )

    if isinstance(target_type, type):
        return mro_distance(obj_type, target_type)

    # Default case
    return float("inf")


def remove_null_type(typehint: Type) -> Type:
    if get_origin(typehint) is Union or isinstance(typehint, types.UnionType):
        return Union[  # type: ignore
            tuple(  # type: ignore
                [t for t in get_args(typehint) if t != type(None)]
            )
        ]
    return typehint
