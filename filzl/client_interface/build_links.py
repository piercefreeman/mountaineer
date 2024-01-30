from typing import Any

from filzl.client_interface.openapi import (
    ActionType,
    OpenAPIDefinition,
    ParameterLocationType,
)
from filzl.client_interface.typescript import (
    TSLiteral,
    map_openapi_type_to_ts,
    python_payload_to_typescript,
)


class OpenAPIToTypescriptLinkConverter:
    """
    Take a OpenAPI definition for how a render() component needs to be accessed. Create a valid typescript
    function to format that page link the with all supported parameters.

    """

    def convert(self, openapi: dict[str, Any]):
        openapi_spec = OpenAPIDefinition(**openapi)

        # We expect there to only be one path in our render router
        if len(openapi_spec.paths) != 1:
            raise ValueError(
                f"Expected only one path in render router, got {list(openapi_spec.paths.keys())}"
            )

        # Extract metadata from this GET definition to fill our link generation
        render_url, render_endpoint_definition = list(openapi_spec.paths.items())[0]
        get_action = next(
            (
                endpoint
                for endpoint in render_endpoint_definition.actions
                if endpoint.action_type == ActionType.GET
            )
        )

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

            input_parameters[TSLiteral(parameter.name)] = TSLiteral(parameter.name)
            typehint_parameters[
                TSLiteral(parameter.name)
                + (TSLiteral("?") if not parameter.required else TSLiteral(""))
            ] = TSLiteral(map_openapi_type_to_ts(parameter.schema_ref.type))

            if parameter.in_location == ParameterLocationType.QUERY:
                query_parameters[TSLiteral(parameter.name)] = TSLiteral(parameter.name)
            elif parameter.in_location == ParameterLocationType.PATH:
                path_parameters[TSLiteral(parameter.name)] = TSLiteral(parameter.name)

        parameter_str = python_payload_to_typescript(input_parameters)
        typehint_str = python_payload_to_typescript(typehint_parameters)
        query_dict_str = python_payload_to_typescript(query_parameters)
        path_dict_str = python_payload_to_typescript(path_parameters)

        lines: list[str] = []

        # Step 1: Parameter string with typehints
        lines.append(f"export const getLink = ({parameter_str} : {typehint_str}) => {{")

        # Step 2: Define our local dictionary to separate query and path parameters
        lines.append(f"let url = '{render_url}';\n")

        lines.append(
            f"const queryParameters : Record<string, string> = {query_dict_str};"
        )
        lines.append(
            f"const pathParameters : Record<string, string> = {path_dict_str};\n"
        )

        # Step 3: We can now loop over our query parameters and add them to our link
        # We assume any undefined parameters are optional, since if they're not they should be
        # flagged during static checking
        lines.append(
            "const parsedParams = Object.entries(queryParameters).reduce((acc, [key, value]) => {\n"
            "if (value !== undefined) {\n"
            "acc.push(`${key}=${value}`);\n"
            "}\n"
            "return acc;\n"
            "}, [] as string[]);\n"
        )
        lines.append("const paramString = parsedParams.join('&');\n")

        # Step 4: For path parameters, we loop over and try to replace them in the raw path
        # If we can't find a parameter, we throw an error
        lines.append(
            "for (const [key, value] of Object.entries(pathParameters)) {\n"
            "if (value === undefined) {\n"
            "throw new Error(`Missing required path parameter ${key}`);\n"
            "}\n"
            "url = url.replace(`{${key}}`, value);\n"
            "}\n"
        )

        # Step 5: Append the query params, if we have any
        lines.append("if (paramString) {\n" "url = `${url}?${paramString}`;\n" "}\n")

        # Step 6: Close the block
        lines.append("return url;")
        lines.append("};")

        return "\n".join(lines)
