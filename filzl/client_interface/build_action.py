from pydantic import BaseModel, Field
from typing import TypedDict, Any
from filzl.client_interface.build_schemas import OpenAPISchemaType, OpenAPIProperty
from enum import StrEnum

class ParameterLocationType(StrEnum):
    PATH = "path"
    QUERY = "query"

class RequestBodyDefinition(BaseModel):
    class ContentDefinition(BaseModel):
        class Reference(BaseModel):
            ref : str = Field(alias="$ref")
        schema_ref: Reference = Field(alias="schema")

    # { content_type: {schema: SchemaDefinition }}
    content: dict[str, ContentDefinition]
    # Requests will typically provider their required status, requests will not.
    # Default these to True since they are required within the scope of the request
    # that is provided.
    required: bool = True

class URLParameterDefinition(BaseModel):
    class Schema(BaseModel):
        type: OpenAPISchemaType
        title: str

        # Specified in the case of a known format that can be validated on the client-side, like a UUID
        format: str | None = None

    name: str
    in_location: ParameterLocationType = Field(alias="in")
    schema_ref: Schema = Field(alias="schema")
    required: bool

class ActionDefinition(BaseModel):
    summary: str
    operationId: str
    # Parameters injected into the URL path
    parameters: list[URLParameterDefinition] = []

    # { status_code: ResponseDefinition }
    responses: dict[str, RequestBodyDefinition]
    requestBody: RequestBodyDefinition | None = None

class EndpointDefinition(BaseModel):
    get: ActionDefinition | None = None
    post: ActionDefinition | None = None
    put: ActionDefinition | None = None
    patch: ActionDefinition | None = None
    delete: ActionDefinition | None = None

class OpenAPIDefinition(BaseModel):
    class Components(BaseModel):
        schemas: dict[str, OpenAPIProperty]

    paths: dict[str, EndpointDefinition]

    components: Components

class OpenAPIToTypescriptActionConverter:
    """
    Parse utilities and typescript construction for building actions
    based on the defined endpoint OpenAPI specs.

    """
    def __init__(self):
        pass

    def convert(self, openapi: dict[str, Any]) -> dict[str, str]:
        """
        :return {function_name: function_body}

        """
        definition = OpenAPIDefinition(**openapi)
        print(definition)
        raise ValueError
