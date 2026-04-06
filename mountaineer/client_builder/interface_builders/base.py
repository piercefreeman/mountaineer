from datetime import date, datetime, time
from inspect import isclass
from json import dumps as json_dumps
from types import NoneType
from typing import Any
from uuid import UUID

from fastapi import UploadFile

from mountaineer.client_builder.parser import (
    EnumWrapper,
    ModelWrapper,
    SelfReference,
)
from mountaineer.client_builder.types import (
    DictOf,
    ListOf,
    LiteralOf,
    Or,
    SetOf,
    TupleOf,
    TypeDefinition,
)
from mountaineer.logging import LOGGER

PRIMITIVE_TYPE_TO_TYPESCRIPT: dict[Any, str] = {
    str: "string",
    int: "number",
    float: "number",
    bool: "boolean",
    # TODO: We should cast this to a Date internally
    datetime: "string",
    date: "string",
    time: "string",
    UploadFile: "Blob",
    UUID: "string",
    None: "null",
    NoneType: "null",
    Any: "any",
}


# TODO: Consolidate this simple-subclass/root-type resolution with iceaxe so both
# packages share one typehint normalization path.
def get_root_primitive_type(py_type: type[Any] | None) -> Any | None:
    if not isclass(py_type):
        return None

    return next(
        (
            candidate
            for candidate in py_type.__mro__[1:]
            if candidate in PRIMITIVE_TYPE_TO_TYPESCRIPT
        ),
        None,
    )


class InterfaceBase:
    """
    Each interface builder owns the responsibility of converting a specific type of object
    to a discrete block of Typescript code. This is the main location where the python
    typehints are formatted into Typescript type annotations.

    """

    @classmethod
    def _get_annotated_value(cls, value):
        """Convert a field type to TypeScript type."""
        if isinstance(value, ModelWrapper):
            return value.name.global_name
        elif isinstance(value, EnumWrapper):
            return value.name.global_name
        else:
            complex_value = cls._handle_complex_type(value, requires_complex=True)
            if complex_value:
                return complex_value
            if isinstance(value, SelfReference):
                return value.name
            primitive_value = cls._map_primitive_type_to_typescript(value)
            if primitive_value:
                return primitive_value
            LOGGER.warning(f"Unable to map value, falling back to generic: {value}")
            return "any"

    @classmethod
    def _map_primitive_type_to_typescript(cls, py_type: type[Any] | None) -> str | None:
        """Map Python types to TypeScript types"""
        if py_type in PRIMITIVE_TYPE_TO_TYPESCRIPT:
            return PRIMITIVE_TYPE_TO_TYPESCRIPT[py_type]

        root_type = get_root_primitive_type(py_type)
        if root_type is None:
            return None
        return PRIMITIVE_TYPE_TO_TYPESCRIPT[root_type]

    @classmethod
    def _handle_complex_type(
        cls, type_hint: Any, requires_complex: bool = False
    ) -> str | None:
        """Handle complex type hints like list[str], dict[str, int], etc."""
        if not isinstance(type_hint, TypeDefinition):
            return None

        if isinstance(type_hint, ListOf):
            return f"Array<{cls._get_annotated_value(type_hint.type)}>"

        if isinstance(type_hint, TupleOf):
            values = [cls._get_annotated_value(t) for t in type_hint.types]
            return f"[{','.join(values)}]"

        if isinstance(type_hint, SetOf):
            return f"Set<{cls._get_annotated_value(type_hint.type)}>"

        if isinstance(type_hint, DictOf):
            return f"Record<{cls._get_annotated_value(type_hint.key_type)}, {cls._get_annotated_value(type_hint.value_type)}>"

        if isinstance(type_hint, Or):
            return " | ".join(cls._get_annotated_value(t) for t in type_hint.children)

        if isinstance(type_hint, LiteralOf):
            return " | ".join(json_dumps(value) for value in type_hint.values)

        raise ValueError(f"Unsupported TypeDefinition type: {type_hint}")
