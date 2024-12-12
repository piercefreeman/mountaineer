from typing import Any

from mountaineer.actions.fields import FunctionActionType
from mountaineer.client_builder.parser import (
    ControllerWrapper,
)
from mountaineer.client_builder.typescript import (
    TSLiteral,
    python_payload_to_typescript,
)


class TypeScriptLinkConverter(BaseTypeScriptConverter):
    """Converts controller routes to TypeScript link generators"""

    def convert_controller_links(self, controller: ControllerWrapper) -> str:
        """Generate link formatter for a controller's routes"""
        if not controller.render:
            return ""
        if not controller.entrypoint_url:
            return ""

        # Collect parameters from render model
        query_parameters: dict[str, Any] = {}
        path_parameters: dict[str, Any] = {}
        query_typehints: dict[str, Any] = {}
        path_typehints: dict[str, Any] = {}

        # Split parameters into query and path
        for field in controller.queries:
            query_parameters[field.name] = TSLiteral(field.name)
            query_typehints[TSLiteral(field.name)] = TSLiteral(
                self._get_field_type(field)
            )

        for field in controller.paths:
            path_parameters[field.name] = TSLiteral(field.name)
            path_typehints[TSLiteral(field.name)] = TSLiteral(
                self._get_field_type(field)
            )

        # Combine all parameters for the function signature
        all_parameters = {**query_parameters, **path_parameters}
        all_typehints = {**query_typehints, **path_typehints}

        return self._generate_link_function(
            controller.entrypoint_url,
            all_parameters,
            all_typehints,
            query_parameters,
            path_parameters,
        )

    def _generate_link_function(
        self,
        url: str,
        parameters: dict[str, Any],
        typehints: dict[str, Any],
        query_parameters: dict[str, Any],
        path_parameters: dict[str, Any],
    ) -> str:
        """Generate the TypeScript link function"""
        param_str = python_payload_to_typescript(parameters)
        typehint_str = python_payload_to_typescript(typehints)

        query_dict_str = python_payload_to_typescript(query_parameters)
        path_dict_str = python_payload_to_typescript(path_parameters)

        chunks = []

        # Function signature with all parameters
        chunks.append(f"export const getLink = ({param_str}: {typehint_str}) => {{")

        # Split parameters into query and path
        chunks.extend(
            [
                f"  const url = `{url}`;",
                f"  const queryParameters: Record<string, any> = {query_dict_str};",
                f"  const pathParameters: Record<string, any> = {path_dict_str};",
                "",
                "  return __getLink({",
                "    rawUrl: url,",
                "    queryParameters,",
                "    pathParameters",
                "  });",
                "}",
            ]
        )

        return "\n".join(chunks)


class TypeScriptServerHookConverter(BaseTypeScriptConverter):
    """Converts controllers to TypeScript server hooks"""

    def convert_controller_hooks(
        self,
        controller: ControllerWrapper,
    ) -> str:
        """Generate useServer hook for a controller"""
        if not controller.render:
            return ""

        render_model = controller.render.name

        imports = self._generate_imports(controller, render_model)
        interface = self._generate_interface(render_model, controller.name)
        hook = self._generate_hook(controller, render_model)

        return "\n\n".join(["\n".join(imports), "\n".join(interface), "\n".join(hook)])

    def _generate_imports(
        self, controller: ControllerWrapper, render_model: str
    ) -> list[str]:
        """Generate import statements"""
        imports = [
            f"import {{ {render_model}, {controller.name} }} from './models';",
        ]

        if controller.all_actions:
            action_imports = [
                f"import {{ {', '.join(action.name for action in controller.all_actions)} }} from './actions';"
            ]
            imports.extend(action_imports)

        return imports

    def _generate_interface(self, render_model: str, controller_id: str) -> list[str]:
        """Generate ServerState interface"""
        return [
            "declare global {",
            "var SERVER_DATA: any;",
            "}",
            "",
            f"export interface ServerState extends {render_model}, {controller_id} {{",
            "  linkGenerator: typeof LinkGenerator;",
            "}",
        ]

    def _generate_hook(
        self, controller: ControllerWrapper, render_model: str
    ) -> list[str]:
        """Generate useServer hook implementation"""
        server_response = {
            TSLiteral("...serverState"): TSLiteral("...serverState"),
            "linkGenerator": TSLiteral("LinkGenerator"),
        }

        for action in controller.all_actions:
            server_response[TSLiteral(action.name)] = (
                TSLiteral(f"applySideEffect({action.name}, setControllerState)")
                if action.action_type == FunctionActionType.SIDEEFFECT
                else TSLiteral(action.name)
            )

        response_body = python_payload_to_typescript(server_response)
        # Special case: refactor to an explicit controller property
        server_key = controller.controller.__name__

        chunks = []
        optional_model_name = f"{render_model}Optional"
        chunks.append(f"export type {optional_model_name} = Partial<{render_model}>;")

        chunks += [
            "export const useServer = () : ServerState => {",
            f"const [serverState, setServerState] = useState(SERVER_DATA['{server_key}'] as {render_model});",
            f"const setControllerState = (payload: {optional_model_name}) => {{",
            "setServerState((state) => ({",
            "...state,",
            "...payload,",
            "}));",
            "};",
            f"return {response_body}",
            "};",
        ]

        return chunks
