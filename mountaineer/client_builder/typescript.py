"""
Utilities to generate some common Typescript objects from
Python definitions.

"""
from typing import Any

from mountaineer.client_builder.openapi import (
    EmptyAPIProperty,
    OpenAPIDefinition,
    OpenAPIProperty,
    OpenAPISchema,
    OpenAPISchemaType,
    URLParameterDefinition,
    resolve_ref,
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
    }
    return mapping[openapi_type]


def get_types_from_parameters(
    schema: OpenAPIProperty | EmptyAPIProperty,
    base_openapi_spec: OpenAPISchema | OpenAPIDefinition | None,
):
    """
    Handle potentially complex types from the parameter schema, like the case
    of optional fields.

    """
    if isinstance(schema, EmptyAPIProperty):
        return "any"

    # Mutually exclusive definitions
    if schema.enum:
        yield " | ".join([f"'{enum_value}'" for enum_value in schema.enum])
    elif schema.variable_type:
        if schema.variable_type == OpenAPISchemaType.ARRAY:
            child_typehint = " | ".join(
                str(value)
                for value in (
                    get_types_from_parameters(schema.items, base_openapi_spec)
                    if schema.items
                    else ["any"]
                )
            )
            yield f"Array<{child_typehint}>"
            # This call should completely wrap all of the sub-types, so we don't
            # allow ourselves to continue down the tree.
            return
        else:
            yield map_openapi_type_to_ts(schema.variable_type)

    # Recursively gather all of the types that might be nested
    for property in schema.properties.values():
        yield from get_types_from_parameters(property, base_openapi_spec)

    if schema.additionalProperties:
        yield from get_types_from_parameters(
            schema.additionalProperties, base_openapi_spec
        )

    if schema.items:
        yield from get_types_from_parameters(schema.items, base_openapi_spec)

    if schema.anyOf:
        for one_of in schema.anyOf:
            yield from get_types_from_parameters(one_of, base_openapi_spec)

    if schema.allOf:
        for all_of in schema.allOf:
            yield from get_types_from_parameters(all_of, base_openapi_spec)

    # If we're able to resolve the ref, do so. Some clients call this to get a limited
    # scope of known parameters, so this value is optional.
    if schema.ref:
        if base_openapi_spec:
            ref = resolve_ref(schema.ref, base_openapi_spec)
            yield from get_types_from_parameters(ref, base_openapi_spec)
        else:
            raise ValueError(
                f"Unexpected $ref in schema: {schema.ref}, no base schema passed for resolution"
            )


def get_typehint_for_parameter(
    parameter: URLParameterDefinition,
    base: OpenAPISchema | OpenAPIDefinition | None = None,
):
    """
    Get the typehint for a parameter, which may be a single type or a union of types.

    Providing the "base" OpenAPI schema allows us to resolve refs. Otherwise we will just
    parse the types directly from the parameter and throw an error on ref resolution.

    """
    parameter_types = set(get_types_from_parameters(parameter.schema_ref, base))

    key = TSLiteral(parameter.name) + (
        TSLiteral("?") if not parameter.required else TSLiteral("")
    )
    value = TSLiteral(
        " | ".join(
            # Sort helps with consistency of generated code
            sorted(parameter_types)
        )
    )

    return key, value
