from typing import Any

from mountaineer.client_builder.openapi import (
    ActionType,
    OpenAPIDefinition,
    ParameterLocationType,
)
from mountaineer.client_builder.typescript import (
    TSLiteral,
    get_typehint_for_parameter,
    python_payload_to_typescript,
)


class OpenAPIToTypescriptLinkConverter:
    """
    Take a OpenAPI definition for how a render() component needs to be accessed. Create a valid typescript
    function to format that page link with all supported parameters.

    """

    def convert(self, openapi: dict[str, Any]):
        openapi_spec = OpenAPIDefinition(**openapi)

        # We expect there to only be one path in our render router
        if len(openapi_spec.paths) != 1:
            raise ValueError(
                f"Expected only one path in render router, got {list(openapi_spec.paths.keys())}"
            )

        # Extract metadata from this GET definition to fill our link generation
        # We require a single get action
        render_payloads = [
            (render_url, endpoint)
            for render_url, render_endpoint_definition in openapi_spec.paths.items()
            for endpoint in render_endpoint_definition.actions
            if endpoint.action_type == ActionType.GET
        ]
        if len(render_payloads) != 1:
            raise ValueError(
                f"Expected exactly one GET action in render router, got {render_payloads}"
            )

        render_url, get_action = render_payloads[0]

        input_parameters: dict[str, Any] = {}
        typehint_parameters: dict[str, Any] = {}

        query_parameters: dict[str, Any] = {}
        path_parameters: dict[str, Any] = {}

        # We can now parse the query and path parameters that this endpoint supports
        for parameter in get_action.parameters:
            # We only support query and path parameters
            if parameter.in_location not in {
                ParameterLocationType.QUERY,
                ParameterLocationType.PATH,
            }:
                continue

            typehint_key, typehint_value = get_typehint_for_parameter(
                parameter,
                openapi_spec,
            )
            input_parameters[TSLiteral(parameter.name)] = TSLiteral(parameter.name)
            typehint_parameters[typehint_key] = typehint_value

            if parameter.in_location == ParameterLocationType.QUERY:
                query_parameters[TSLiteral(parameter.name)] = TSLiteral(parameter.name)
            elif parameter.in_location == ParameterLocationType.PATH:
                path_parameters[TSLiteral(parameter.name)] = TSLiteral(parameter.name)

        parameter_str = python_payload_to_typescript(input_parameters)
        typehint_str = python_payload_to_typescript(typehint_parameters)
        query_dict_str = python_payload_to_typescript(query_parameters)
        path_dict_str = python_payload_to_typescript(path_parameters)

        chunks: list[str] = []

        # Step 1: Parameter string with typehints
        chunks.append(
            f"export const getLink = ({parameter_str} : {typehint_str}) => {{"
        )

        # Step 2: Define our local dictionary to separate query and path parameters
        # We need to do this in the actual view controller itself because only in the backend
        # code we have an explicit delineation between query and path parameters. To the getLink
        # input function they both look the same.
        chunks.append(f"const url = `{render_url}`;")

        chunks.append(
            f"const queryParameters : Record<string, any> = {query_dict_str};\n"
            f"const pathParameters : Record<string, any> = {path_dict_str};"
        )

        # Delegate the core processing logic to our global helper since the rest of the logic
        # is shared across every link generator
        chunks.append(
            "return __getLink({rawUrl: url, queryParameters, pathParameters});"
        )

        chunks.append("};")

        return "\n\n".join(chunks)
