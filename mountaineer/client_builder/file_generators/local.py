from typing import Any
from mountaineer.client_builder.file_generators.base import CodeBlock, FileGeneratorBase
from mountaineer.client_builder.interface_builders.controller import ControllerInterface
from mountaineer.client_builder.interface_builders.action import ActionInterface
from mountaineer.client_builder.parser import ControllerWrapper, EnumWrapper, ModelWrapper
from mountaineer.client_builder.typescript import TSLiteral, python_payload_to_typescript
from mountaineer.paths import ManagedViewPath, generate_relative_import

class LocalGeneratorBase(FileGeneratorBase):
    def __init__(self, *, managed_path: ManagedViewPath, global_root: ManagedViewPath):
        super().__init__(managed_path)
        self.global_root = global_root

    def get_global_import_path(self, global_name: str):
        """
        Gets the relative path from the current file to the desired global file. This
        allows for typescript imports in the same workflow.

        """
        root_common_handler = self.global_root / global_name
        return generate_relative_import(
            self.managed_path, root_common_handler
        )

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
        yield CodeBlock(
            f"import {{ __getLink }} from '{api_import_path}';"
        )

        yield CodeBlock(
            self._convert_controller_links(self.controller)
        )

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
            TSLiteral("pathParameters"): TSLiteral("pathParameters")
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
            ActionInterface.from_action(
                action, parsed_controller.url_prefix or ""
            )
            for action in parsed_controller.wrapper.all_actions
        ]

        return [
            typescript_action.to_js() for typescript_action in all_actions
        ]

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

        exports : list[str] = []

        # Add controller exports
        exports += list(self._add_controller_exports(
            self.controller, controller_import_path
        ))

        # Add model exports
        if self.controller.render:
            exports += list(self._add_model_exports(
                self.controller.render, controller_import_path
            ))

        for action in self.controller.all_actions:
            if action.request_body:
                exports += list(self._add_model_exports(action.request_body, controller_import_path))
            if action.response_body:
                exports += list(self._add_model_exports(action.response_body, exports, controller_import_path))

        yield CodeBlock(*exports)

    def _add_controller_exports(
        self, controller: ControllerWrapper, import_path: str
    ):
        yield f"export type {{ {controller.name} }} from '{import_path}';"

    def _add_model_exports(
        self, model: ModelWrapper, import_path: str
    ):
        """Add export statements for a model and its dependencies"""
        # Export superclasses first
        for superclass in model.superclasses:
            yield self._add_model_exports(superclass, import_path)

        # Export model
        yield f"export type {{ {model.name} }} from '{import_path}';"

        # Export dependencies (models + enums)
        # TODO: Deduplicate this, potentially with a common method to get all unique types
        # from the implicit graph that's constructed through superclasses
        for field in model.value_models:
            if isinstance(field.value, ModelWrapper):
                yield from self._add_model_exports(field.value, import_path)
            elif isinstance(field.value, EnumWrapper):
                yield f"export type {{ {field.value.name} }} from '{import_path}';"

class UseServerGenerator:
    def _generate_view_servers(self):
        """Generate useServer hooks for each controller"""
        for controller_id, parsed_controller in self.parsed_controllers.items():
            if not parsed_controller.wrapper.render:
                continue

            controller_dir = parsed_controller.view_path.get_managed_code_dir()

            controller_model_path = self.view_root.get_controller_view_path(
                parsed_controller.wrapper.controller
            ).get_managed_code_dir()
            global_server_path = self.view_root.get_managed_code_dir()
            relative_server_path = generate_relative_import(
                controller_model_path, global_server_path
            )

            imports = [
                "import React, { useState } from 'react';",
                f"import {{ applySideEffect }} from '{relative_server_path}/api';",
                f"import LinkGenerator from '{relative_server_path}/links';",
            ]

            script = self.hook_converter.convert_controller_hooks(
                parsed_controller.wrapper
            )

            # Write the complete file
            (controller_dir / "useServer.ts").write_text(
                self.formatter.format("\n".join(imports) + "\n" + script)
            )

class LocalIndexGenerator:

    def _generate_index_files(self):
        """Generate index files for each controller"""
        for controller_id, parsed_controller in self.parsed_controllers.items():
            controller_dir = parsed_controller.view_path.get_managed_code_dir()

            exports = []
            for module in ["actions", "links", "models", "useServer"]:
                module_file = controller_dir / f"{module}.ts"
                if module_file.exists() and module_file.read_text().strip():
                    exports.append(f"export * from './{module}';")

            (controller_dir / "index.ts").write_text("\n".join(exports))
