"""
Generator for TypeScript interfaces from OpenAPI specifications.
"""
import json
from typing import Any, Optional, Union, Iterator, Type, get_args, get_origin, Dict
from pydantic import BaseModel, Field, model_validator
from enum import StrEnum
from filzl.annotation_helpers import get_value_by_alias, yield_all_subtypes


class OpenAPISchemaType(StrEnum):
    OBJECT = "object"
    STRING = "string"
    INTEGER = "integer"
    FLOAT = "float"
    BOOLEAN = "boolean"
    ARRAY = "array"
    # Typically used to indicate an optional type within an anyOf statement
    NULL = "null"

class OpenAPIProperty(BaseModel):
    title: str | None = None
    properties: dict[str, "OpenAPIProperty"] = {}
    additionalProperties: Optional["OpenAPIProperty"] = None
    required: list[str] = []

    # Self-contained type: object, int, etc
    variable_type: OpenAPISchemaType | None = Field(alias="type", default=None)
    # Reference to another type
    ref: str | None = Field(alias="$ref", default=None)
    # Array of another type
    items: Optional["OpenAPIProperty"] = None
    # Pointer to multiple possible subtypes
    anyOf: list["OpenAPIProperty"] = []

    # Validator to ensure that one of the optional values is set
    @model_validator(mode="after")
    def check_provided_value(self) -> "OpenAPIProperty":
        if not any([self.variable_type, self.ref, self.items, self.anyOf]):
            raise ValueError("One of variable_type, $ref, or items must be set")
        return self

    def __hash__(self):
        # Normally we would make use of a frozen BaseClass to enable hashing, but since
        # dictionaries are included in the payload here an easier way is just to convert
        # to a JSON string and hash that.
        # We make sure to order the strings since otherwise the hash risks being different
        # despite having the same values
        def sort_json(obj):
            if isinstance(obj, dict):
                return sorted((k, sort_json(v)) for k, v in obj.items())
            else:
                return obj
        return hash(json.dumps(sort_json(self.model_dump())))

class OpenAPISchema(OpenAPIProperty):
    defs : dict[str, OpenAPIProperty] = Field(alias="$defs", default_factory=dict)

class OpenAPIToTypeScriptConverter:
    def convert(self, model: Type[BaseModel]):
        self.validate_typescript_candidate(model)

        openapi_spec = model.model_json_schema()
        print("RAW SPEC", openapi_spec)
        schema = OpenAPISchema(**openapi_spec)
        print("PARSED SPEC", schema)
        return self.convert_to_typescript(schema)

    def convert_to_typescript(self, parsed_spec: OpenAPISchema):
        #components = parsed_spec.get('components', {})
        #schemas = components.get('schemas', {})

        # Fetch all the dependent models
        all_models = list(self.gather_all_models(parsed_spec))

        # We put in one big models.ts file to enable potentially cyclical dependencies
        ts_interfaces = [
            self.convert_schema_to_interface(model, base=parsed_spec)
            for model in all_models
        ]

        return "\n\n".join(ts_interfaces)

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

    def resolve_ref(self, ref: str, base: OpenAPISchema) -> OpenAPIProperty:
        current_obj : OpenAPIProperty = base
        for part in ref.split("/"):
            if part == "#":
                current_obj = base
            else:
                try:
                    current_obj = get_value_by_alias(current_obj, part)
                except AttributeError as e:
                    raise AttributeError(f"Invalid $ref, couldn't resolve path: {ref}") from e
        return current_obj

    def convert_schema_to_interface(self, model: OpenAPIProperty, base: OpenAPISchema):
        fields = []

        # We have to support arrays with one and multiple values
        def walk_array_types(prop: OpenAPIProperty) -> Iterator[str]:
            print("WALKING TYPE", prop)
            if prop.ref:
                yield self.get_typescript_interface_name(self.resolve_ref(prop.ref, base=base))
            elif prop.items:
                yield from walk_array_types(prop.items)
            elif prop.anyOf:
                for sub_prop in prop.anyOf:
                    yield from walk_array_types(sub_prop)
            elif prop.additionalProperties:
                # OpenAPI doesn't specify the type of the keys since JSON forces them to be strings
                # By the time we get to this function we should have called validate_typescript_candidate
                sub_types = " | ".join(walk_array_types(prop.additionalProperties))
                yield f"Record<str, {sub_types}>"
            elif prop.variable_type:
                yield self.map_openapi_type_to_ts(prop.variable_type)

        for prop_name, prop_details in model.properties.items():
            is_required = prop_name in model.required
            ts_type = self.map_openapi_type_to_ts(prop_details.variable_type) if prop_details.variable_type else None

            annotation_str = " | ".join(set(walk_array_types(prop_details)))
            ts_type = ts_type.format(types=annotation_str) if ts_type else annotation_str

            fields.append(f"  {prop_name}{'?' if not is_required else ''}: {ts_type};")

        interface_body = "\n".join(fields)
        return f"interface {self.get_typescript_interface_name(model)} {{\n{interface_body}\n}}"

    def map_openapi_type_to_ts(self, openapi_type: OpenAPISchemaType):
        mapping = {
            'string': 'string',
            'integer': 'number',
            'number': 'number',
            'boolean': 'boolean',
            'null': 'null',
            'array': 'Array<{types}>',
            'object': '{types}',
        }
        return mapping[openapi_type]

    def get_typescript_interface_name(self, model: OpenAPIProperty):
        if not model.title:
            raise ValueError(f"Model must have a title to retrieve its typescript name: {model}")
        return model.title.replace(" ", "")

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
                    raise ValueError(f"Key must be a string for JSON dictionary serialization. Received `{typehint}`.")
