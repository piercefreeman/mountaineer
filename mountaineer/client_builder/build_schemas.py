"""
Generator for TypeScript interfaces from OpenAPI specifications.
"""
from typing import Any, Dict, Iterator, Type, get_args, get_origin

from inflection import camelize
from pydantic import BaseModel, create_model

from mountaineer.annotation_helpers import yield_all_subtypes
from mountaineer.client_builder.openapi import (
    EmptyAPIProperty,
    OpenAPIDefinition,
    OpenAPIProperty,
    OpenAPISchema,
    OpenAPISchemaType,
    gather_all_models,
    resolve_ref,
)
from mountaineer.client_builder.typescript import (
    TSLiteral,
    map_openapi_type_to_ts,
    python_payload_to_typescript,
)
from mountaineer.logging import LOGGER


class OpenAPIToTypescriptSchemaConverter:
    """
    Transform a pydantic.BaseModel into a TypeScript interface, by using
    OpenAPI as an intermediate layer. This also allows client callers to support
    generating interfaces from other OpenAPI-compliant schemas.

    """

    def __init__(self, export_interface: bool = False):
        self.export_interface = export_interface

    def get_model_json_schema(self, model: Type[BaseModel]):
        """
        By default pydantic will still include exclude=True parameters in the
        OpenAPI schema. This helper function creates a synthetic model
        before conversion so we exclude these unnecessary parameters.

        """
        self.validate_typescript_candidate(model)

        include_fields = {
            field: (field_info.annotation, field_info)
            for field, field_info in model.model_fields.items()
            if not field_info.exclude
        }

        synthetic_model = create_model(
            model.__name__,
            __config__=model.model_config,
            **include_fields,  # type: ignore
        )

        return synthetic_model.model_json_schema()

    def convert_schema_to_typescript(
        self,
        parsed_spec: OpenAPISchema,
        all_fields_required: bool = False,
    ):
        # Fetch all the dependent models
        all_models = list(gather_all_models(parsed_spec))

        return {
            model.title: self.convert_schema_to_interface(
                model,
                base=parsed_spec,
                all_fields_required=all_fields_required,
            )
            for model in all_models
            if model.title and model.title.strip()
        }

    def convert_schema_to_interface(
        self,
        model: OpenAPIProperty,
        base: OpenAPISchema | OpenAPIDefinition,
        all_fields_required: bool,
    ):
        if model.variable_type == OpenAPISchemaType.OBJECT:
            return self._convert_object_to_interface(
                model,
                base,
                all_fields_required=all_fields_required,
            )
        elif model.enum is not None:
            return self._convert_enum_to_interface(model)
        else:
            raise ValueError(f"Unknown model type: {model}")

    def _convert_object_to_interface(
        self,
        model: OpenAPIProperty,
        base: OpenAPISchema | OpenAPIDefinition,
        all_fields_required: bool,
    ):
        fields = []

        # We have to support arrays with one and multiple values
        def walk_array_types(prop: OpenAPIProperty | EmptyAPIProperty) -> Iterator[str]:
            if isinstance(prop, EmptyAPIProperty):
                yield "any"
                return

            if prop.variable_type == OpenAPISchemaType.ARRAY:
                # Special case for arrays where we shouldn't use the Array syntax
                if prop.prefixItems:
                    tuple_values = [
                        " | ".join(sorted(set(walk_array_types(item))))
                        for item in prop.prefixItems
                    ]
                    yield f"[{', '.join(tuple_values)}]"
                    return

                array_types: list[str] = (
                    sorted(set(walk_array_types(prop.items))) if prop.items else ["any"]
                )
                yield f"Array<{' | '.join(array_types)}>"
            elif prop.ref:
                yield self.get_typescript_interface_name(
                    resolve_ref(prop.ref, base=base)
                )
            elif prop.items:
                yield from walk_array_types(prop.items)
            elif prop.anyOf:
                for sub_prop in prop.anyOf:
                    yield from walk_array_types(sub_prop)
            elif prop.additionalProperties:
                # OpenAPI doesn't specify the type of the keys since JSON forces them to be strings
                # By the time we get to this function we should have called validate_typescript_candidate
                sub_types = " | ".join(
                    sorted(set(walk_array_types(prop.additionalProperties)))
                )
                yield f"Record<{map_openapi_type_to_ts(OpenAPISchemaType.STRING)}, {sub_types}>"
            elif prop.const:
                yield python_payload_to_typescript(prop.const)
            elif prop.variable_type:
                # Should be the very last type to parsed, since all the other switch
                # statements are more specific than a simple variable type
                yield map_openapi_type_to_ts(prop.variable_type, format=prop.format)
            else:
                LOGGER.warning(f"Unknown property type: {prop}")

        for prop_name, prop_details in model.properties.items():
            is_required = (prop_name in model.required) or all_fields_required

            # Sort types for determinism in tests and built code
            ts_type = " | ".join(sorted(set(walk_array_types(prop_details))))

            if prop_details.description:
                fields.append("  /**")
                fields.append(f"   * {prop_details.description}")
                fields.append("   */")

            fields.append(f"  {prop_name}{'?' if not is_required else ''}: {ts_type};")

        interface_body = "\n".join(fields)
        interface_full = f"interface {self.get_typescript_interface_name(model)} {{\n{interface_body}\n}}"

        if self.export_interface:
            interface_full = f"export {interface_full}"

        return interface_full

    def _convert_enum_to_interface(self, model: OpenAPIProperty):
        fields: dict[str, Any] = {}

        if not model.enum:
            raise ValueError(f"Model {model} is not an enum")

        for enum_value in model.enum:
            # If the enum is an integer, we need to escape it
            enum_key: str
            if isinstance(enum_value, (int, float)):
                enum_key = f"Value__{enum_value}"
            elif isinstance(enum_value, str):
                enum_key = camelize(enum_value, uppercase_first_letter=True)
            else:
                raise ValueError(f"Invalid enum value: {enum_value}")

            fields[TSLiteral(enum_key)] = enum_value

        # Enums use an equal assignment syntax
        interface_body = python_payload_to_typescript(fields).replace(":", " =")
        interface_full = (
            f"enum {self.get_typescript_interface_name(model)} {interface_body}"
        )

        if self.export_interface:
            interface_full = f"export {interface_full}"

        return interface_full

    def get_typescript_interface_name(self, model: OpenAPIProperty):
        if not model.title:
            raise ValueError(
                f"Model must have a title to retrieve its typescript name: {model}"
            )

        replace_chars = {" ", "[", "]"}
        values = model.title

        for char in replace_chars:
            values = values.strip(char)
            values = values.replace(char, "_")

        return camelize(values)

    def validate_typescript_candidate(self, model: Type[BaseModel]):
        """
        JSON only supports some types, so we need to validate that the given model not only
        is valid in Python but will also be valid when serialized over the wire.

        """
        for typehint in yield_all_subtypes(model):
            origin = get_origin(typehint)
            args = get_args(typehint)
            if origin and origin in {dict, Dict}:
                # We only support keys that are strings
                if args and not issubclass(args[0], str):
                    raise ValueError(
                        f"Key must be a string for JSON dictionary serialization. Received `{typehint}`."
                    )
