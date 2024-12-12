from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from shutil import rmtree as shutil_rmtree
from time import monotonic_ns
from typing import Dict, Type

from inflection import camelize
from pydantic import BaseModel

from mountaineer.app import AppController
from mountaineer.client_builder.converters import (
    TypeScriptActionConverter,
    TypeScriptGenerator,
    TypeScriptLinkConverter,
    TypeScriptServerHookConverter,
)
from mountaineer.client_builder.formatter import TypeScriptFormatter
from mountaineer.client_builder.parser import (
    ControllerParser,
    ControllerWrapper,
    EnumWrapper,
    ModelWrapper,
)
from mountaineer.client_builder.typescript import (
    TSLiteral,
    normalize_interface,
    python_payload_to_typescript,
)
from mountaineer.console import CONSOLE
from mountaineer.controller_layout import LayoutControllerBase as LayoutControllerBase
from mountaineer.paths import ManagedViewPath, generate_relative_import
from mountaineer.static import get_static_path


@dataclass
class ParsedController:
    """Represents a fully parsed controller with its associated paths and metadata"""

    wrapper: ControllerWrapper
    view_path: ManagedViewPath
    url_prefix: str | None = None
    is_layout: bool = False


class APIBuilder:
    """
    Main entrypoint for building the auto-generated typescript code. This includes
    the server provided API used by useServer.
    """

    def __init__(
        self,
        app: AppController,
        live_reload_port: int | None = None,
        build_cache: Path | None = None,
    ):
        self.app = app
        self.live_reload_port = live_reload_port
        self.build_cache = build_cache
        self.view_root = ManagedViewPath.from_view_root(app._view_root)

        # Initialize parser
        self.parser = ControllerParser()
        self.formatter = TypeScriptFormatter()

        # Initialize converters
        self.root_controller_converter = TypeScriptGenerator(export_interface=True)
        self.action_converter = TypeScriptActionConverter()
        self.link_converter = TypeScriptLinkConverter()
        self.hook_converter = TypeScriptServerHookConverter()

        # Store parsed results
        self.parsed_controllers: Dict[str, ParsedController] = {}

    async def build_all(self):
        # Totally clear away the old build cache, so we start fresh
        # and don't have additional files hanging around
        for clear_dir in [
            self.view_root.get_managed_ssr_dir(),
            self.view_root.get_managed_static_dir(),
        ]:
            if clear_dir.exists():
                shutil_rmtree(clear_dir)

        await self.build_use_server()
        # await self.build_fe_diff(None)

    async def build_use_server(self):
        start = monotonic_ns()

        with CONSOLE.status("Building useServer", spinner="dots"):
            # Parse all controllers first
            self._parse_all_controllers()
            self._assign_unique_names()

            # Generate all the required files
            self._generate_static_files()
            self._generate_model_definitions()
            self._generate_action_definitions()
            self._generate_link_shortcuts()
            self._generate_link_aggregator()
            self._generate_view_servers()
            self._generate_index_files()

        CONSOLE.print(
            f"[bold green]🔨 Built useServer in {(monotonic_ns() - start) / 1e9:.2f}s"
        )

    def _parse_all_controllers(self):
        """Parse all controllers and store their parsed representations"""
        self.parsed_controllers.clear()

        for controller_def in self.app.controllers:
            controller = controller_def.controller
            # TODO: REMOVE
            controller_id = (
                f"{controller.__class__.__module__}.{controller.__class__.__name__}"
            )

            # Parse the controller
            parsed_wrapper = self.parser.parse_controller(controller.__class__)

            # Get view path
            # view_path = self.view_root.get_controller_view_path(controller)
            view_path = self.view_root.get_controller_view_path(controller)

            # Create ParsedController instance
            self.parsed_controllers[controller_id] = ParsedController(
                wrapper=parsed_wrapper,
                view_path=view_path,
                url_prefix=controller_def.url_prefix,
                is_layout=isinstance(controller, LayoutControllerBase),
            )

    def _assign_unique_names(self):
        """Assign unique names to potentially duplicate models, enums, controllers, etc"""
        reference_counts = Counter()

        # Each of these dictionaries are keyed with the actual classes in memory themselves, so
        # any values should be unique representations of different logical classes
        for model in self.parser.parsed_models.values():
            model.name = normalize_interface(model.name)
            reference_counts.update([model.name])
        for self_reference in self.parser.parsed_self_references:
            self_reference.name = normalize_interface(self_reference.name)
            # No need to update the reference counts, since we expect these to just
            # point to an existing model anyway
        for enum in self.parser.parsed_enums.values():
            enum.name = normalize_interface(enum.name)
            reference_counts.update([enum.name])
        for controller in self.parser.parsed_controllers.values():
            controller.name = normalize_interface(controller.name)
            reference_counts.update([controller.name])

        # Any reference counts that have more than one reference need to be uniquified
        duplicate_names = {
            name for name, count in reference_counts.items() if count > 1
        }

        converted_models: dict[Type[BaseModel], str] = {}

        for model in self.parser.parsed_models.values():
            if model.name in duplicate_names:
                prefix = self._typescript_prefix_from_module(model.model.__module__)
                model.name = f"{prefix}_{model.name}"
                converted_models[model.model] = model.name
        for self_reference in self.parser.parsed_self_references:
            if self_reference.model in converted_models:
                self_reference.name = converted_models[self_reference.model]
        for enum in self.parser.parsed_enums.values():
            if enum.name in duplicate_names:
                prefix = self._typescript_prefix_from_module(enum.enum.__module__)
                enum.name = f"{prefix}_{enum.name}"
        for controller in self.parser.parsed_controllers.values():
            if controller.name in duplicate_names:
                prefix = self._typescript_prefix_from_module(
                    controller.controller.__module__
                )
                controller.name = f"{prefix}_{controller.name}"

    def _generate_static_files(self):
        """Copy over static files required for the client"""
        managed_code_dir = self.view_root.get_managed_code_dir()
        for static_file in ["api.ts", "live_reload.ts"]:
            content = get_static_path(static_file).read_text()
            (managed_code_dir / static_file).write_text(content)

    def _generate_model_definitions(self):
        """Generate TypeScript interfaces for all models"""
        global_code_dir = self.view_root.get_managed_code_dir()

        # Generate all controller base definitions
        schemas_content = self.root_controller_converter.generate_definitions(
            [controller.wrapper for controller in self.parsed_controllers.values()]
        )

        # Write global schemas
        (global_code_dir / "controllers.ts").write_text(
            self.formatter.format(schemas_content)
        )

        # Generate per-controller model files that will import the global definitions locally
        for controller_id, parsed_controller in self.parsed_controllers.items():
            controller_dir = parsed_controller.view_path.get_managed_code_dir()
            imports = generate_relative_import(
                controller_dir / "models.ts", global_code_dir / "controllers.ts"
            )

            exports = [
                f"export type {{ {parsed_controller.wrapper.name} }} from '{imports}';"
            ]

            # Add model exports
            if parsed_controller.wrapper.render:
                self._add_model_exports(
                    parsed_controller.wrapper.render, exports, imports
                )

            for action in parsed_controller.wrapper.all_actions:
                if action.request_body:
                    self._add_model_exports(action.request_body, exports, imports)
                if action.response_body:
                    self._add_model_exports(action.response_body, exports, imports)

            (controller_dir / "models.ts").write_text(
                self.formatter.format("\n".join(exports))
            )

    def _add_model_exports(
        self, model: ModelWrapper, exports: list[str], import_path: str
    ):
        """Add export statements for a model and its dependencies"""
        # Export superclasses first
        for superclass in model.superclasses:
            self._add_model_exports(superclass, exports, import_path)

        # Export model
        exports.append(f"export type {{ {model.name} }} from '{import_path}';")

        # Export dependencies (models + enums)
        # TODO: Deduplicate this, potentially with a common method to get all unique types
        # from the implicit graph that's constructed through superclasses
        for field in model.value_models:
            if isinstance(field.value, ModelWrapper):
                self._add_model_exports(field.value, exports, import_path)
            elif isinstance(field.value, EnumWrapper):
                exports.append(
                    f"export type {{ {field.value.name} }} from '{import_path}';"
                )

    def _generate_action_definitions(self):
        """Generate TypeScript action definitions for all controllers"""
        for controller_id, parsed_controller in self.parsed_controllers.items():
            if not parsed_controller.wrapper.actions:
                continue

            controller_dir = parsed_controller.view_path.get_managed_code_dir()
            root_code_dir = self.view_root.get_managed_code_dir()

            controller_action_path = controller_dir / "actions.ts"
            root_common_handler = root_code_dir / "api.ts"
            root_api_import_path = generate_relative_import(
                controller_action_path, root_common_handler
            )

            # Convert each action. We also include the superclass methods, since they're
            # actually bound to the controller instance with separate urls.
            all_actions = [
                self.action_converter.convert_action(
                    action.name, action, parsed_controller.url_prefix or ""
                )
                for action in parsed_controller.wrapper.all_actions
            ]

            actions_ts = [
                typescript_action.to_js() for typescript_action in all_actions
            ]

            deps = set()
            for action in parsed_controller.wrapper.all_actions:
                if action.request_body:
                    deps.add(action.request_body.name)
                if action.response_body:
                    deps.add(action.response_body.name)

            # Generate imports
            imports = [
                f"import {{ __request, FetchErrorBase }} from '{root_api_import_path}';",
                f"import type {{ {', '.join(deps)} }} from './models';",
            ]

            (controller_dir / "actions.ts").write_text(
                self.formatter.format("\n\n".join(imports + actions_ts))
            )

    def _generate_link_shortcuts(self):
        """Generate TypeScript link formatters for each controller"""
        for controller_id, parsed_controller in self.parsed_controllers.items():
            if parsed_controller.is_layout:
                continue

            controller_dir = parsed_controller.view_path.get_managed_code_dir()
            root_code_dir = self.view_root.get_managed_code_dir()

            controller_links_path = controller_dir / "links.ts"

            root_common_handler = root_code_dir / "api.ts"
            root_api_import_path = generate_relative_import(
                controller_links_path, root_common_handler
            )

            # Generate link content
            link_content = self.link_converter.convert_controller_links(
                parsed_controller.wrapper
            )

            if link_content:
                content = [
                    f"import {{ __getLink }} from '{root_api_import_path}';\n",
                    "",
                    link_content,
                ]
                controller_links_path.write_text(
                    self.formatter.format("\n".join(content))
                )
            else:
                controller_links_path.write_text("")

    def _generate_link_aggregator(self):
        """Generate global link aggregator"""
        imports = []
        link_setters = {}
        global_dir = self.view_root.get_managed_code_dir()

        for controller_id, parsed_controller in self.parsed_controllers.items():
            if parsed_controller.is_layout:
                continue

            controller_dir = parsed_controller.view_path.get_managed_code_dir()
            rel_import = generate_relative_import(
                global_dir / "links.ts", controller_dir / "links.ts"
            )

            # Add import and setter for this controller
            local_name = f"{parsed_controller.wrapper.name}GetLinks"
            imports.append(f"import {{ getLink as {local_name} }} from '{rel_import}';")
            link_setters[
                # Mirror the lowercase camelcase convention of previous versions
                camelize(
                    parsed_controller.wrapper.controller.__name__,
                    uppercase_first_letter=False,
                )
            ] = TSLiteral(local_name)

        content = [
            *imports,
            "",
            f"const linkGenerator = {python_payload_to_typescript(link_setters)};",
            "",
            "export default linkGenerator;",
        ]

        (global_dir / "links.ts").write_text(self.formatter.format("\n".join(content)))

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

    def _typescript_prefix_from_module(self, module: str):
        module_parts = module.split(".")
        return "".join([camelize(component) for component in module_parts])
