from pydantic import BaseModel, Field, model_validator
from typing import Any
from filzl.client_interface.build_schemas import OpenAPISchemaType, OpenAPIProperty
from enum import StrEnum
from inflection import underscore
from filzl.client_interface.typescript import python_payload_to_typescript, TSLiteral


class ParameterLocationType(StrEnum):
    PATH = "path"
    QUERY = "query"


class ActionType(StrEnum):
    GET = "get"
    POST = "post"
    PUT = "put"
    PATCH = "patch"
    DELETE = "delete"


class ContentDefinition(BaseModel):
    class Reference(BaseModel):
        ref: str = Field(alias="$ref")

    schema_ref: Reference = Field(alias="schema")


class RequestBodyDefinition(BaseModel):
    # original key is a `content: { content_type: {schema: SchemaDefinition }}`
    content_type: str
    content_schema: ContentDefinition

    # Requests will typically provider their required status, requests will not.
    # Default these to True since they are required within the scope of the request
    # that is provided.
    required: bool = True

    @model_validator(mode="before")
    def explode_content_dictionary(cls, data: Any) -> Any:
        if "content" not in data or not isinstance(data["content"], dict):
            raise ValueError("RequestBodyDefinition.content must be a dict")

        # We only support a single content type for now
        if len(data["content"]) != 1:
            raise ValueError(
                "RequestBodyDefinition.content must have a single content type"
            )

        data["content_type"], data["content_schema"] = list(data["content"].items())[0]

        return data


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
    action_type: ActionType

    summary: str
    operationId: str
    # Parameters injected into the URL path
    parameters: list[URLParameterDefinition] = []

    # { status_code: ResponseDefinition }
    responses: dict[str, RequestBodyDefinition]
    requestBody: RequestBodyDefinition | None = None


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


class OpenAPIDefinition(BaseModel):
    class Components(BaseModel):
        schemas: dict[str, OpenAPIProperty]

    # { path: { action: ActionDefinition }}
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
        schema = OpenAPIDefinition(**openapi)
        for url, endpoint_definition in schema.paths.items():
            for action, method_name in zip(
                endpoint_definition.actions,
                self.get_method_names(url, endpoint_definition.actions),
            ):
                self.build_action(url, action, method_name)
        raise ValueError

    def build_action(self, url: str, action: ActionDefinition, method_name: str):
        # Since our typescript common functions have variable inputs here, it's cleaner
        # to put them into a dictionary and format whatever made it in as a flat
        # input list.
        response_types: list[str] = []
        common_params: dict[str, Any] = {
            "method": action.action_type.upper(),
            "url": url,
            "path": {},
            "errors": {},
        }

        if action.requestBody is not None:
            common_params["body"] = TSLiteral("requestBody")
            common_params["mediaType"] = action.requestBody.content_type

        if action.parameters:
            for parameter in action.parameters:
                common_params["path"][parameter.name] = TSLiteral(parameter.name)

        for status_code, response_definition in action.responses.items():
            status_int = int(status_code)
            if status_int >= 200 and status_int < 300:
                # OK response, we can specify the expected response type
                # Multiple OK responses for a single action is unusual, but again we support it
                response_types.append(
                    self.get_typescript_name_from_content_definition(
                        response_definition.content_schema
                    )
                )
            else:
                common_params["errors"][
                    status_int
                ] = self.get_typescript_name_from_content_definition(
                    response_definition.content_schema
                )

        formatted_config = python_payload_to_typescript(common_params)
        print(formatted_config)

    def get_method_names(self, url: str, actions: list[ActionDefinition]):
        # By convention, the last part of the URL is the method name
        base_method_name = underscore(url.split("/")[-1])

        method_names: list[str] = []

        # For the most part, actions will only have one type of request parameter associated
        # with them but this might not always be true. In the cases of a conflict we can
        # uniquely define the typescript name by appending the action type
        if len(actions) > 1:
            # By the time we get to this function, none of the passed actions should
            # have null action types
            for action in actions:
                if action.action_type is None:
                    raise ValueError(f"Action {action} is missing an action type")
                method_names.append(f"{base_method_name}_{action.action_type.lower()}")
        else:
            method_names.append(base_method_name)

        return method_names

    def get_typescript_name_from_content_definition(
        self, definition: ContentDefinition
    ):
        return definition.schema_ref.ref.split("/")[-1]
