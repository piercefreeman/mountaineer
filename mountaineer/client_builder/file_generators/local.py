from typing import Any

from mountaineer.actions.fields import FunctionActionType
from mountaineer.client_builder.file_generators.base import CodeBlock, FileGeneratorBase
from mountaineer.client_builder.interface_builders.action import ActionInterface
from mountaineer.client_builder.interface_builders.controller import ControllerInterface
from mountaineer.client_builder.parser import (
    ControllerWrapper,
)
from mountaineer.client_builder.typescript import (
    TSLiteral,
    python_payload_to_typescript,
)
from mountaineer.paths import ManagedViewPath, generate_relative_import


class LocalGeneratorBase(FileGeneratorBase):
    def __init__(self, *, managed_path: ManagedViewPath, global_root: ManagedViewPath):
        super().__init__(managed_path=managed_path)
        self.global_root = global_root

    def get_global_import_path(self, global_name: str):
        """
        Gets the relative path from the current file to the desired global file. This
        allows for typescript imports in the same workflow.

        """
        root_common_handler = self.global_root / global_name
        return generate_relative_import(self.managed_path, root_common_handler)


class LocalLinkGenerator(LocalGeneratorBase):
    def __init__(
        self,
        controller: ControllerWrapper,
        *,
        managed_path: ManagedViewPath,
        global_root: ManagedViewPath,
    ):
        super().__init__(managed_path=managed_path, global_root=global_root)
        self.controller = controller

    def script(self):
        if self.controller.is_layout:
            return

        api_import_path = self.get_global_import_path("api.ts")
        yield CodeBlock(f"import {{ __getLink }} from '{api_import_path}';")

        yield CodeBlock(self._convert_controller_links(self.controller))

    def _convert_controller_links(self, controller: ControllerWrapper) -> str:
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
                ControllerInterface._get_annotated_value(field.value)
            )

        for field in controller.paths:
            path_parameters[field.name] = TSLiteral(field.name)
            path_typehints[TSLiteral(field.name)] = TSLiteral(
                ControllerInterface._get_annotated_value(field.value)
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

        link_args = {
            TSLiteral("rawUrl"): TSLiteral("url"),
            TSLiteral("queryParameters"): TSLiteral("queryParameters"),
            TSLiteral("pathParameters"): TSLiteral("pathParameters"),
        }

        link_logic = [
            f"const url = `{url}`;\n",
            f"const queryParameters: Record<string, any> = {query_dict_str};",
            f"const pathParameters: Record<string, any> = {path_dict_str};\n",
            CodeBlock.indent(f"return __getLink({link_args});"),
        ]
        link_logic_str = "\n".join(link_logic)

        # Function signature with all parameters
        lines = [
            f"export const getLink = ({param_str}: {typehint_str}) => {{",
            CodeBlock.indent(f"  {link_logic_str}"),
            "};",
        ]

        return "\n".join(lines)


class LocalActionGenerator(LocalGeneratorBase):
    def __init__(
        self,
        controller: ControllerWrapper,
        *,
        managed_path: ManagedViewPath,
        global_root: ManagedViewPath,
    ):
        super().__init__(managed_path=managed_path, global_root=global_root)
        self.controller = controller

    def script(self):
        action_js = self._generate_controller_actions(self.controller)
        dependencies = self._get_dependent_imports(self.controller)

        # Generate imports
        api_import_path = self.get_global_import_path("api.ts")
        yield CodeBlock(
            f"import {{ __request, FetchErrorBase }} from '{api_import_path}';",
            f"import type {{ {', '.join(dependencies)} }} from './models';",
        )

        # Generate actions
        for action in action_js:
            yield CodeBlock(action)

    def _generate_controller_actions(self, parsed_controller: ControllerWrapper):
        """
        Generate all actions that are either owned directly by this controller
        or one of the parents, since they'll be separately mounted to this endpoint.

        """
        # Convert each action. We also include the superclass methods, since they're
        # actually bound to the controller instance with separate urls.
        all_actions = [
            ActionInterface.from_action(action, parsed_controller.url_prefix or "")
            for action in parsed_controller.wrapper.all_actions
        ]

        return [typescript_action.to_js() for typescript_action in all_actions]

    def _get_dependent_imports(self, parsed_controller: ControllerWrapper):
        deps = set()
        for action in parsed_controller.wrapper.all_actions:
            if action.request_body:
                deps.add(action.request_body.name)
            if action.response_body:
                deps.add(action.response_body.name)
        return deps


class LocalModelGenerator(LocalGeneratorBase):
    """
    Re-export the globally defined models that are owned (or used) by this
    given controller. This makes IDE type introspection easier for the current
    project file by isolating the models that are involved. We also add alias
    definitions to these imports so even if we were forced to rename the models
    in the global state they'll be the expected definitions here.

    These should mirror the code class names 1:1, with the exception of any
    classes that are both used by the controller and share the same name
    in the global space across different imported files.

    """

    def __init__(
        self,
        controller: ControllerWrapper,
        *,
        managed_path: ManagedViewPath,
        global_root: ManagedViewPath,
    ):
        super().__init__(managed_path=managed_path, global_root=global_root)
        self.controller = controller

    def script(self):
        controller_import_path = self.get_global_import_path("controllers.ts")

        controllers = ControllerWrapper.get_all_embedded_controllers([self.controller])
        models, enums = ControllerWrapper.get_all_embedded_types(
            [self.controller], include_superclasses=True
        )

        yield CodeBlock(
            *[
                f"export type {{ {controller.name} }} from '{controller_import_path}';"
                for controller in controllers
            ]
        )

        yield CodeBlock(
            *[
                f"export type {{ {model.name} }} from '{controller_import_path}';"
                for model in models
            ]
        )

        yield CodeBlock(
            *[
                f"export type {{ {enum.name} }} from '{controller_import_path}';"
                for enum in enums
            ]
        )


class LocalUseServerGenerator(LocalGeneratorBase):
    def __init__(
        self,
        controller: ControllerWrapper,
        *,
        managed_path: ManagedViewPath,
        global_root: ManagedViewPath,
    ):
        super().__init__(managed_path=managed_path, global_root=global_root)
        self.controller = controller

    def script(self):
        if not self.controller.render:
            return

        api_import_path = self.get_global_import_path("api.ts")
        links_import_path = self.get_global_import_path("links.ts")
        yield CodeBlock(
            "import React, { useState } from 'react';",
            f"import {{ applySideEffect }} from '{api_import_path}';",
            f"import LinkGenerator from '{links_import_path}';",
        )

        # Verify in this parent function that render is a non-None value
        render_model_name = self.controller.render.name

        yield from self._generate_imports(self.controller, render_model_name)
        yield from self._generate_interface(self.controller, render_model_name)
        yield from self._generate_hook(self.controller, render_model_name)

    def _generate_imports(self, controller: ControllerWrapper, render_model: str):
        """Generate import statements"""
        imports = [
            f"import {{ {render_model}, {controller.name} }} from './models';",
        ]

        if controller.all_actions:
            imports.append(
                f"import {{ {', '.join(action.name for action in controller.all_actions)} }} from './actions';"
            )

        yield CodeBlock(*imports)

    def _generate_interface(self, controller: ControllerWrapper, render_model: str):
        """Generate ServerState interface"""
        yield CodeBlock("declare global {", "  var SERVER_DATA: any;", "}")

        yield CodeBlock(
            f"export interface ServerState extends {render_model}, {controller.name} {{",
            "  linkGenerator: typeof LinkGenerator;",
            "}",
        )

    def _generate_hook(self, controller: ControllerWrapper, render_model: str):
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

        optional_model_name = f"{render_model}Optional"
        yield CodeBlock(f"export type {optional_model_name} = Partial<{render_model}>;")

        yield CodeBlock(
            "export const useServer = () : ServerState => {",
            f"  const [serverState, setServerState] = useState(SERVER_DATA['{server_key}'] as {render_model});\n",
            f"  const setControllerState = (payload: {optional_model_name}) => {{",
            "    setServerState((state) => ({",
            "      ...state,",
            "      ...payload,",
            "    }));",
            "  };\n",
            f"  return {response_body}",
            "};",
        )


class LocalIndexGenerator(LocalGeneratorBase):
    def __init__(
        self,
        controller: ControllerWrapper,
        *,
        managed_path: ManagedViewPath,
        global_root: ManagedViewPath,
    ):
        super().__init__(managed_path=managed_path, global_root=global_root)
        self.controller = controller

    def script(self):
        exports = []
        for module in ["actions", "links", "models", "useServer"]:
            module_file = self.managed_path / f"{module}.ts"
            if module_file.exists() and module_file.read_text().strip():
                exports.append(f"export * from './{module}';")

        yield CodeBlock(*exports)
