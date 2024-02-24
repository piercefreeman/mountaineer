"""
Generator for TypeScript interfaces from OpenAPI specifications.
"""
from typing import Dict, Iterator, Type, get_args, get_origin

from inflection import camelize
from pydantic import BaseModel, create_model

from mountaineer.annotation_helpers import get_value_by_alias, yield_all_subtypes
from mountaineer.client_builder.openapi import (
    OpenAPIProperty,
    OpenAPISchema,
    OpenAPISchemaType,
)
from mountaineer.client_builder.typescript import map_openapi_type_to_ts


class OpenAPIToTypescriptSchemaConverter:
    """
    Transform a pydantic.BaseModel into a TypeScript interface, by using
    OpenAPI as an intermediate layer. This also allows client callers to support
    generating interfaces from other OpenAPI-compliant schemas.

    """

    def __init__(self, export_interface: bool = False):
        self.export_interface = export_interface

    def convert(self, model: Type[BaseModel]):
        self.validate_typescript_candidate(model)

        openapi_spec = self.get_model_json_schema(model)
        schema = OpenAPISchema(**openapi_spec)
        return self.convert_to_typescript(schema)

    def get_model_json_schema(self, model: Type[BaseModel]):
        """
        By default pydantic will still include exclude=True parameters in the
        OpenAPI schema. This helper function creates a synthetic model
        before conversion so we exclude these unnecessary parameters.

        """
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

    def convert_to_typescript(self, parsed_spec: OpenAPISchema):
        # components = parsed_spec.get('components', {})
        # schemas = components.get('schemas', {})

        # Fetch all the dependent models
        all_models = list(self.gather_all_models(parsed_spec))

        return {
            model.title: self.convert_schema_to_interface(model, base=parsed_spec)
            for model in all_models
            if model.title and model.title.strip()
        }

    def gather_all_models(self, base: OpenAPISchema):
        """
        Return all unique models that are used in the given OpenAPI schema. This allows clients
        to build up all of the dependencies that the core model needs.

        :param base: The core OpenAPI Schema
        """

        def walk_models(property: OpenAPIProperty) -> Iterator[OpenAPIProperty]:
            if property.variable_type == OpenAPISchemaType.OBJECT:
                yield property
            if property.ref is not None:
                yield from walk_models(self.resolve_ref(property.ref, base))
            if property.items:
                yield from walk_models(property.items)
            if property.anyOf:
                for prop in property.anyOf:
                    yield from walk_models(prop)
            for prop in property.properties.values():
                yield from walk_models(prop)
            if property.additionalProperties:
                yield from walk_models(property.additionalProperties)

        return list(set(walk_models(base)))

    def resolve_ref(self, ref: str, base: BaseModel) -> OpenAPIProperty:
        """
        Resolve a $ref that points to a propery-compliant schema in the same document. If this
        ref points somewhere else in the document (that is valid but not a data model) than we
        raise a ValueError.

        """
        current_obj = base
        for part in ref.split("/"):
            if part == "#":
                current_obj = base
            else:
                try:
                    current_obj = get_value_by_alias(current_obj, part)
                except AttributeError as e:
                    raise AttributeError(
                        f"Invalid $ref, couldn't resolve path: {ref}"
                    ) from e
        if not isinstance(current_obj, OpenAPIProperty):
            raise ValueError(f"Resolved $ref is not a valid OpenAPIProperty: {ref}")
        return current_obj

    def convert_schema_to_interface(self, model: OpenAPIProperty, base: BaseModel):
        fields = []

        # We have to support arrays with one and multiple values
        def walk_array_types(prop: OpenAPIProperty) -> Iterator[str]:
            if prop.ref:
                yield self.get_typescript_interface_name(
                    self.resolve_ref(prop.ref, base=base)
                )
            elif prop.items:
                yield from walk_array_types(prop.items)
            elif prop.anyOf:
                for sub_prop in prop.anyOf:
                    yield from walk_array_types(sub_prop)
            elif prop.additionalProperties:
                # OpenAPI doesn't specify the type of the keys since JSON forces them to be strings
                # By the time we get to this function we should have called validate_typescript_candidate
                sub_types = " | ".join(walk_array_types(prop.additionalProperties))
                yield f"Record<{map_openapi_type_to_ts(OpenAPISchemaType.STRING)}, {sub_types}>"
            elif prop.variable_type:
                yield map_openapi_type_to_ts(prop.variable_type)

        for prop_name, prop_details in model.properties.items():
            is_required = prop_name in model.required
            ts_type = (
                map_openapi_type_to_ts(prop_details.variable_type)
                if prop_details.variable_type
                else None
            )

            annotation_str = " | ".join(set(walk_array_types(prop_details)))
            ts_type = (
                ts_type.format(types=annotation_str) if ts_type else annotation_str
            )

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

    def get_typescript_interface_name(self, model: OpenAPIProperty):
        if not model.title:
            raise ValueError(
                f"Model must have a title to retrieve its typescript name: {model}"
            )
        return camelize(model.title)

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
