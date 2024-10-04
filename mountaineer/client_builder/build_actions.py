from typing import Any

from inflection import camelize, underscore

from mountaineer.client_builder.openapi import (
    ActionDefinition,
    ContentDefinition,
    OpenAPIDefinition,
    ParameterLocationType,
)
from mountaineer.client_builder.typescript import (
    TSLiteral,
    get_typehint_for_parameter,
    python_payload_to_typescript,
)
from mountaineer.constants import STREAM_EVENT_TYPE


class OpenAPIToTypescriptActionConverter:
    """
    Parse utilities and typescript construction for building actions
    based on the defined endpoint OpenAPI specs.

    """

    def convert(self, openapi: dict[str, Any]) -> tuple[dict[str, str], list[str]]:
        """
        Our conversion pipeline focuses on creating the action definitions of one file.

        :return {function_name: function_body}, imports required by the function bodies

        """
        schema = OpenAPIDefinition(**openapi)
        output_actions: dict[str, str] = {}
        output_errors: dict[str, str] = {}
        all_required_types: set[str] = set()
        for url, endpoint_definition in schema.paths.items():
            for action, method_name in zip(
                endpoint_definition.actions,
                self.get_method_names(url, endpoint_definition.actions),
            ):
                rendered_str, required_types = self.build_action(
                    url, action, method_name
                )
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
                    422: ValidationErrorException,
                },
            });
        }
        """
        arguments, response_types = self.build_action_payload(url, action)
        parameters, request_types = self.build_action_parameters(action)

        lines: list[str] = []

        response_type_template: str
        if action.media_type == STREAM_EVENT_TYPE:
            response_type_template = (
                "Promise<AsyncGenerator<{response_type}, void, unknown>>"
            )
        else:
            response_type_template = "Promise<{response_type}>"

        if action.is_raw_response:
            response_type = response_type_template.format(response_type="Response")
        else:
            response_type = response_type_template.format(
                response_type=" | ".join(response_types)
            )

        lines.append(
            f"export const {method_name} = ({parameters}): {response_type} => {{\n"
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
        error_classes: dict[str, str] = {}
        required_types: list[str] = []
        for error_code, response in action.responses.items():
            status_int = int(error_code)
            if self.status_code_is_valid(status_int):
                continue
            if not response.content_schema.schema_ref.ref:
                continue

            model_name = response.content_schema.schema_ref.ref.split("/")[-1]
            error_classes[
                model_name
            ] = f"export class {self.get_exception_class_name(model_name)} extends FetchErrorBase<{model_name}> {{}}"
            required_types.append(model_name)

        return error_classes, required_types

    def build_action_parameters(self, action: ActionDefinition):
        parameters_dict: dict[Any, Any] = {}
        typehint_dict: dict[Any, Any] = {}
        request_types: list[str] = []

        for parameter in action.parameters:
            typehint_key, typehint_value = get_typehint_for_parameter(parameter)
            if parameter.in_location in {
                ParameterLocationType.COOKIE,
                ParameterLocationType.HEADER,
            }:
                continue
            parameters_dict[parameter.name] = TSLiteral(parameter.name)
            typehint_dict[typehint_key] = typehint_value

        if (
            action.requestBody is not None
            and action.requestBody.content_schema.schema_ref.ref
        ):
            # We expect that the interface defined within the /models.ts will have the same name as
            # the model in the current OpenAPI spec
            model_name = camelize(
                action.requestBody.content_schema.schema_ref.ref.split("/")[-1]
            )
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
            "query": {},
            "errors": {},
        }

        if action.requestBody is not None:
            common_params["body"] = TSLiteral("requestBody")
            common_params["mediaType"] = action.requestBody.content_type

        if action.parameters:
            for parameter in action.parameters:
                if parameter.in_location == ParameterLocationType.PATH:
                    common_params["path"][parameter.name] = TSLiteral(parameter.name)
                elif parameter.in_location == ParameterLocationType.QUERY:
                    common_params["query"][parameter.name] = TSLiteral(parameter.name)
                elif parameter.in_location in {
                    ParameterLocationType.COOKIE,
                    ParameterLocationType.HEADER,
                }:
                    # No-op, cookies will be sent automatically by fetch()
                    continue
                else:
                    raise NotImplementedError(
                        f"Parameter location {parameter.in_location} not supported"
                    )

        for status_code, response_definition in action.responses.items():
            status_int = int(status_code)
            if self.status_code_is_valid(status_int):
                # OK response, we can specify the expected response type
                # Multiple OK responses for a single action is unusual, but again we support it
                if not action.is_raw_response:
                    response_types.append(
                        self.get_typescript_name_from_content_definition(
                            response_definition.content_schema,
                            url=url,
                            status_code=status_int,
                        )
                    )
            else:
                error_typehint = self.get_typescript_name_from_content_definition(
                    response_definition.content_schema,
                    url=url,
                    status_code=status_int,
                )
                common_params["errors"][status_int] = TSLiteral(
                    # Provide a mapping to the error class
                    self.get_exception_class_name(error_typehint)
                )

        # Remove the optional keys that don't have any values
        for optional_parameter in ["errors", "path", "query"]:
            if not common_params[optional_parameter]:
                del common_params[optional_parameter]

        # Support for server-events
        if action.media_type == STREAM_EVENT_TYPE:
            common_params["eventStreamResponse"] = True

        # Support for raw responses
        if action.is_raw_response:
            common_params["outputFormat"] = "raw"

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
        self,
        definition: ContentDefinition,
        # Url and status are provided for more context about where the error
        # is being thrown. Can pass None if not available.
        url: str | None = None,
        status_code: int | None = None,
    ):
        if not definition.schema_ref.ref:
            raise ValueError(
                f"Content definition {definition} does not have a schema reference.\n"
                f"Double check your action definition for {url} with response code {status_code}.\n"
                "Are you typehinting your response with a Pydantic BaseModel?"
            )
        return definition.schema_ref.ref.split("/")[-1]

    def status_code_is_valid(self, status_code: int):
        return status_code >= 200 and status_code < 300

    def get_exception_class_name(self, exception_typehint: str):
        """
        Given an error like "HTTPValidationError", responds with a class name of
        "HTTPValidationErrorException"

        """
        return f"{exception_typehint}Exception"
