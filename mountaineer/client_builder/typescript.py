"""
Utilities to generate some common Typescript objects from
Python definitions.

"""
from typing import Any

from mountaineer.client_builder.openapi import (
    OpenAPISchemaType,
    URLParameterDefinition,
    get_types_from_parameters,
)


class TSLiteral(str):
    """
    This string should not be quoted when used in a Typescript insert.
    """

    def __add__(self, other):
        # Concatenate self (TSLiteral) with other (any string)
        # and return a new TSLiteral object
        if isinstance(other, str):
            return TSLiteral(super(TSLiteral, self).__add__(other))
        return NotImplemented

    def __radd__(self, other):
        # Handle right-side addition, where a string is added to a TSLiteral
        if isinstance(other, str):
            return TSLiteral(other.__add__(self))
        return NotImplemented


def python_payload_to_typescript(payload: Any) -> str:
    """
    Take an element with python tokens that should be outputted to
    Typescript and consolidate them into a valid payload.

    """
    if isinstance(payload, dict):
        # Convert the children
        children_lines: list[str] = []
        for key, value in payload.items():
            if isinstance(value, TSLiteral):
                # If the literal is the same as the key, we don't need to include it since it's referencing
                # the same variable.
                if key == value:
                    children_lines.append(key)
                    continue

            key = python_payload_to_typescript(key)
            value = python_payload_to_typescript(value)
            children_lines.append(f"{key}: {value}")

        children_str = ",\n".join(children_lines)
        return f"{{\n{children_str}\n}}"
    elif isinstance(payload, list):
        children_lines = [python_payload_to_typescript(child) for child in payload]
        children_str = ",\n".join(children_lines)
        return f"[\n{children_str}\n]"
    elif isinstance(payload, TSLiteral):
        return payload
    elif isinstance(payload, str):
        return f"'{payload}'"
    elif isinstance(payload, bool):
        return str(payload).lower()
    elif isinstance(payload, (int, float)):
        return str(payload)
    elif payload is None:
        return "null"
    else:
        raise ValueError(
            f"Unknown payload type {type(payload) } for Typescript conversion."
        )


def map_openapi_type_to_ts(openapi_type: OpenAPISchemaType):
    mapping = {
        "string": "string",
        "integer": "number",
        "number": "number",
        "boolean": "boolean",
        "null": "null",
        "array": "Array<{types}>",
        "object": "{types}",
    }
    return mapping[openapi_type]


def get_typehint_for_parameter(parameter: URLParameterDefinition):
    """
    Get the typehint for a parameter, which may be a single type or a union of types.

    """
    parameter_types = set(get_types_from_parameters(parameter.schema_ref))

    key = TSLiteral(parameter.name) + (
        TSLiteral("?") if not parameter.required else TSLiteral("")
    )
    value = TSLiteral(
        " | ".join(
            # Sort helps with consistency of generated code
            sorted([map_openapi_type_to_ts(raw_type) for raw_type in parameter_types])
        )
    )

    return key, value
