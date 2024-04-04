import json
from enum import StrEnum
from typing import Any, Optional

from pydantic import BaseModel, Field, model_validator

#
# Enum definitions
#


class OpenAPISchemaType(StrEnum):
    OBJECT = "object"
    STRING = "string"
    INTEGER = "integer"
    FLOAT = "float"
    BOOLEAN = "boolean"
    ARRAY = "array"
    # Typically used to indicate an optional type within an anyOf statement
    NULL = "null"


class ParameterLocationType(StrEnum):
    # https://swagger.io/specification: Parameter Object
    PATH = "path"
    QUERY = "query"

    # https://swagger.io/docs/specification/authentication/cookie-authentication/
    COOKIE = "cookie"
    HEADER = "header"


class ActionType(StrEnum):
    GET = "get"
    POST = "post"
    PUT = "put"
    PATCH = "patch"
    DELETE = "delete"


#
# Nested schemas inside OpenAPI definitions
#


class OpenAPIProperty(BaseModel):
    """
    A property is the core wrapper for OpenAPI model objects. It allows users to recursively
    define data structures based on their type. Each property can have a list of subproperties, alongside
    the constraints of how they're used (ie. required attributes, union of attributes, etc).

    """

    title: str | None = None
    description: str | None = None
    properties: dict[str, "OpenAPIProperty"] = {}
    additionalProperties: Optional["OpenAPIProperty"] = None
    required: list[str] = []

    # Just specified on the leaf object
    format: str | None = None

    # Self-contained type: object, int, etc
    variable_type: OpenAPISchemaType | None = Field(alias="type", default=None)
    # Reference to another type
    ref: str | None = Field(alias="$ref", default=None)
    # Array of another type
    items: Optional["OpenAPIProperty"] = None
    # Enum type
    enum: list[Any] | None = None

    default: Any | None = None

    # Pointer to multiple possible subtypes
    anyOf: list["OpenAPIProperty"] = []

    model_config = {"populate_by_name": True}

    # Validator to ensure that one of the optional values is set
    @model_validator(mode="after")
    def check_provided_value(self: "OpenAPIProperty") -> "OpenAPIProperty":
        if not any([self.variable_type, self.ref, self.items, self.anyOf, self.enum]):
            raise ValueError(
                "One of variable_type, $ref, anyOf, enum, or items must be set"
            )
        return self

    @classmethod
    def from_meta(
        cls,
        title: str | None = None,
        description: str | None = None,
        properties: dict[str, "OpenAPIProperty"] = {},
        additional_properties: Optional["OpenAPIProperty"] = None,
        required: list[str] = [],
        format: str | None = None,
        variable_type: OpenAPISchemaType | None = None,
        ref: str | None = None,
        items: Optional["OpenAPIProperty"] = None,
        enum: list[Any] | None = None,
        anyOf: list["OpenAPIProperty"] = [],
    ) -> "OpenAPIProperty":
        return cls.model_validate(
            {
                "title": title,
                "description": description,
                "properties": properties,
                "additionalProperties": additional_properties,
                "required": required,
                "format": format,
                "type": variable_type,
                "$ref": ref,
                "items": items,
                "enum": enum,
                "anyOf": anyOf,
            }
        )

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


class ContentDefinition(BaseModel):
    class Reference(BaseModel):
        ref: str | None = Field(default=None, alias="$ref")

        model_config = {"populate_by_name": True}

        @classmethod
        def from_meta(cls, ref: str) -> "ContentDefinition.Reference":
            # Workaround to pyright overriding the instance method with
            # the alias, but we can't create attributes with these dynamic types
            return cls.model_validate({"$ref": ref})

    schema_ref: Reference = Field(alias="schema")

    model_config = {"populate_by_name": True}

    @classmethod
    def from_meta(cls, schema_ref: Reference) -> "ContentDefinition":
        return cls.model_validate({"schema": schema_ref})


class ContentBodyDefinition(BaseModel):
    # original key is a `content: { content_type: {schema: SchemaDefinition }}`
    content_type: str
    content_schema: ContentDefinition

    # Requests will typically provider their required status, requests will not.
    # Default these to True since they are required within the scope of the request
    # that is provided.
    required: bool = True

    @model_validator(mode="before")
    def explode_content_dictionary(cls, data: Any) -> Any:
        # If we're being invoked programatically, we will have the required fields
        programatic_construction = data.get("content_type") and data.get(
            "content_schema"
        )

        if programatic_construction:
            return data

        # If we're being invoked from a JSON payload, we expect a content dictionary with a single
        # key/value that provides the specification for content type/content. Explode it so it maps
        # to our variables.
        if "content" not in data or not isinstance(data["content"], dict):
            raise ValueError("ContentBodyDefinition.content must be a dict")

        # We only support a single content type for now
        if len(data["content"]) != 1:
            raise ValueError(
                "RequestBodyDefinition.content must have a single content type"
            )

        data["content_type"], data["content_schema"] = list(data["content"].items())[0]
        return data


class URLParameterDefinition(BaseModel):
    name: str
    in_location: ParameterLocationType = Field(alias="in")
    schema_ref: OpenAPIProperty = Field(alias="schema")
    required: bool

    model_config = {"populate_by_name": True}

    @classmethod
    def from_meta(
        cls,
        name: str,
        in_location: ParameterLocationType,
        schema_ref: OpenAPIProperty,
        required: bool,
    ) -> "URLParameterDefinition":
        return cls.model_validate(
            {
                "name": name,
                "in": in_location,
                "schema": schema_ref,
                "required": required,
            }
        )


class ActionDefinition(BaseModel):
    action_type: ActionType

    summary: str
    operationId: str
    # Parameters injected into the URL path
    parameters: list[URLParameterDefinition] = []

    # { status_code: ResponseDefinition }
    responses: dict[str, ContentBodyDefinition]
    requestBody: ContentBodyDefinition | None = None

    # Custom Mountaineer event types specified in the OpenAPI schema
    # These should all have defaults since they're optional
    media_type: str | None = None
    is_raw_response: bool = False


class EndpointDefinition(BaseModel):
    actions: list[ActionDefinition] = []

    @model_validator(mode="before")
    def inject_action_type(cls, data: Any) -> dict[str, Any]:
        """
        OpenAPI often defines metadata in a dict structure where the key is relevant
        to the behavior of the values. In our pipeline we want to be able to pass
        around ActionDefinitions to fully generate a resulting type action. We migrate
        the key-metadata into the actual definition itself.

        """
        if not isinstance(data, dict):
            raise ValueError("EndpointDefinition must be a dict")

        for action_type, payload in data.items():
            payload["action_type"] = action_type

        return {"actions": data.values()}


#
# Top-level OpenAPI definition entrypoints. These parse the high level spec.
#


class OpenAPISchema(OpenAPIProperty):
    """
    Defines the expected format for model-only definition schemas. This
    is the output when Pydantic is called with `model_json_schema`.

    """

    defs: dict[str, OpenAPIProperty] = Field(alias="$defs", default_factory=dict)


class OpenAPIDefinition(BaseModel):
    """
    Defines the spec for a whole OpenAPI API definition. This mirrors what FastAPI
    outputs as the /openapi.json endpoint.

    """

    class Components(BaseModel):
        schemas: dict[str, OpenAPIProperty]

    # { path: { action: ActionDefinition }}
    paths: dict[str, EndpointDefinition]
    components: Components = Components(schemas={})


#
# Helper methods
#


def get_types_from_parameters(schema: OpenAPIProperty):
    """
    Handle potentially complex types from the parameter schema, like the case
    of optional fields.

    """
    # Recursively gather all of the types that might be nested
    if schema.variable_type:
        yield schema.variable_type

    for property in schema.properties.values():
        yield from get_types_from_parameters(property)

    if schema.additionalProperties:
        yield from get_types_from_parameters(schema.additionalProperties)

    if schema.items:
        yield from get_types_from_parameters(schema.items)

    if schema.anyOf:
        for one_of in schema.anyOf:
            yield from get_types_from_parameters(one_of)

    # We don't expect $ref values in the URL schema, if we do then the parsing
    # is likely incorrect
    if schema.ref:
        raise ValueError(f"Unexpected $ref in URL schema: {schema.ref}")
