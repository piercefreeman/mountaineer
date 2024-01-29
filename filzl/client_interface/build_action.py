from pydantic import BaseModel, Field, model_validator
from typing import Any
from filzl.client_interface.build_schemas import OpenAPISchemaType, OpenAPIProperty
from enum import StrEnum
from inflection import underscore
from filzl.client_interface.typescript import python_payload_to_typescript, TSLiteral, map_openapi_type_to_ts


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
    responses: dict[str, ContentBodyDefinition]
    requestBody: ContentBodyDefinition | None = None


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
    def convert(self, openapi: dict[str, Any]):
        """
        :return {function_name: function_body}

        """
        schema = OpenAPIDefinition(**openapi)
        output_actions : dict[str, str] = {}
        output_errors : dict[str, str] = {}
        all_required_types : set[str] = set()
        for url, endpoint_definition in schema.paths.items():
            for action, method_name in zip(
                endpoint_definition.actions,
                self.get_method_names(url, endpoint_definition.actions),
            ):
                rendered_str, required_types = self.build_action(url, action, method_name)
                error_strs, error_types = self.build_error(action)

                output_actions[method_name] = rendered_str
                output_errors.update(error_strs)
                all_required_types.update(required_types)
                all_required_types.update(error_types)

        return {**output_actions, **output_errors}, list(all_required_types)

    def build_action(self, url: str, action: ActionDefinition, method_name: str):
        """
        Builds the action function. This should be more-or-less compatible with the common
        server fetch provided by `openapi-typescript-codegen`. Example return value:

        public static my_action({
            param_id,
            requestBody,
        }: {
            param_id: string;
            requestBody: MyActionRequest;
        }): CancelablePromise<any> {
            return __request(OpenAPI, {
                method: 'POST',
                url: '/{param_id}/my_action',
                path: {
                    param_id,
                },
                body: requestBody,
                mediaType: 'application/json',
                errors: {
                    422: ValidationErrorError,
                },
            });
        }
        """
        arguments, response_types = self.build_action_payload(url, action)
        parameters, request_types = self.build_action_parameters(action)

        lines : list[str] = []

        lines.append(
            f"export const {method_name} = ({parameters}): Promise<{' | '.join(response_types)}> => {{\n"
            + "return __request(\n"
            + arguments
            + "\n);\n"
            + "}"
        )
        return "\n".join(lines), list(set(request_types + response_types))

    def build_error(self, action: ActionDefinition):
        """
        Build an error class that wraps the typehinted error contents payload.
        """
        error_classes : dict[str, str] = {}
        required_types: list[str] = []
        for error_code, response in action.responses.items():
            status_int = int(error_code)
            if self.status_code_is_valid(status_int):
                continue

            model_name = response.content_schema.schema_ref.ref.split("/")[-1]
            error_classes[model_name] = f"class {self.get_exception_class_name(model_name)} extends FetchErrorBase<{model_name}> {{}}"
            required_types.append(model_name)

        return error_classes, required_types

    def build_action_parameters(self, action: ActionDefinition):
        parameters_dict : dict[Any, Any] = {}
        typehint_dict : dict[Any, Any] = {}
        request_types : list[str] = []

        for parameter in action.parameters:
            parameters_dict[parameter.name] = TSLiteral(parameter.name)
            typehint_dict[TSLiteral(parameter.name)] = TSLiteral(map_openapi_type_to_ts(parameter.schema_ref.type))

        if action.requestBody is not None:
            # We expect that the interface defined within the /models.ts will have the same name as
            # the model in the current OpenAPI spec
            model_name = action.requestBody.content_schema.schema_ref.ref.split("/")[-1]
            parameters_dict["requestBody"] = TSLiteral("requestBody")
            typehint_dict[TSLiteral("requestBody")] = TSLiteral(model_name)
            request_types.append(model_name)

        if not parameters_dict:
            # Empty query parameter
            return "", request_types

        parameters_str = python_payload_to_typescript(parameters_dict)
        typehint_str = python_payload_to_typescript(typehint_dict)

        return f"{parameters_str}: {typehint_str}", request_types

    def build_action_payload(self, url: str, action: ActionDefinition):
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
            if self.status_code_is_valid(status_int):
                # OK response, we can specify the expected response type
                # Multiple OK responses for a single action is unusual, but again we support it
                response_types.append(
                    self.get_typescript_name_from_content_definition(
                        response_definition.content_schema
                    )
                )
            else:
                error_typehint = self.get_typescript_name_from_content_definition(
                    response_definition.content_schema
                )
                common_params["errors"][
                    status_int
                ] = TSLiteral(
                    # Provide a mapping to the error class
                    self.get_exception_class_name(error_typehint)
                )

        # Remove the optional keys that don't have any values
        for optional_parameter in ["errors", "path"]:
            if not common_params[optional_parameter]:
                del common_params[optional_parameter]

        return python_payload_to_typescript(common_params), response_types

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

    def status_code_is_valid(self, status_code: int):
        return status_code >= 200 and status_code < 300

    def get_exception_class_name(self, exception_typehint: str):
        """
        Given an error like "HTTPValidationError", responds with a class name of
        "HTTPValidationErrorException"

        """
        return f"{exception_typehint}Exception"
