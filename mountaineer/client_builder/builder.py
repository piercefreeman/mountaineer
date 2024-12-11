from dataclasses import dataclass
from pathlib import Path
from shutil import rmtree as shutil_rmtree
from typing import Dict

from mountaineer.app import AppController
from mountaineer.client_builder.converters import (
    TypeScriptActionConverter,
    TypeScriptGenerator,
    TypeScriptLinkConverter,
    TypeScriptServerHookConverter,
)
from mountaineer.client_builder.parser import (
    ControllerParser,
    ControllerWrapper,
    ModelWrapper,
)
from mountaineer.client_builder.typescript import normalize_interface
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

        # Initialize converters
        self.root_controller_converter = TypeScriptGenerator(export_interface=True)
        self.action_converter = TypeScriptActionConverter()
        self.link_converter = TypeScriptLinkConverter()
        self.hook_converter = TypeScriptServerHookConverter()

        # Store parsed results
        self.parsed_controllers: Dict[str, ParsedController] = {}

    async def build_all(self):
        """Main build entrypoint that orchestrates the entire build process"""
        # Clear old build artifacts
        for clear_dir in [
            self.view_root.get_managed_ssr_dir(),
            self.view_root.get_managed_static_dir(),
        ]:
            if clear_dir.exists():
                shutil_rmtree(clear_dir)

        # Parse all controllers first
        self._parse_all_controllers()

        # Generate all the required files
        self._generate_static_files()
        self._generate_model_definitions()
        self._generate_action_definitions()
        self._generate_link_shortcuts()
        self._generate_link_aggregator()
        self._generate_view_servers()
        self._generate_index_files()

    def _parse_all_controllers(self):
        """Parse all controllers and store their parsed representations"""
        self.parsed_controllers.clear()

        for controller_def in self.app.controllers:
            controller = controller_def.controller
            controller_id = controller.__class__.__name__

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
            self.parsed_controllers
        )

        # Write global schemas
        (global_code_dir / "controllers.ts").write_text(schemas_content)

        # Generate per-controller model files
        for controller_id, parsed_controller in self.parsed_controllers.items():
            controller_dir = parsed_controller.view_path.get_managed_code_dir()
            imports = generate_relative_import(
                controller_dir / "models.ts", global_code_dir / "controllers.ts"
            )

            exports = [f"export type {{ {controller_id} }} from '{imports}';"]

            # Add model exports
            if parsed_controller.wrapper.render:
                self._add_model_exports(
                    parsed_controller.wrapper.render, exports, imports
                )

            for action in parsed_controller.wrapper.actions.values():
                if action.request_body:
                    self._add_model_exports(action.request_body, exports, imports)
                if action.response_body:
                    self._add_model_exports(action.response_body, exports, imports)

            (controller_dir / "models.ts").write_text("\n".join(exports))

    def _add_model_exports(
        self, model: ModelWrapper, exports: list[str], import_path: str
    ):
        """Add export statements for a model and its dependencies"""
        # Export superclasses first
        for superclass in model.superclasses:
            self._add_model_exports(superclass, exports, import_path)

        # Export model
        exports.append(
            f"export type {{ {normalize_interface(model.model.__name__)} }} from '{import_path}';"
        )

    def _generate_action_definitions(self):
        """Generate TypeScript action definitions for all controllers"""
        for controller_id, parsed_controller in self.parsed_controllers.items():
            if not parsed_controller.wrapper.actions:
                continue

            controller_dir = parsed_controller.view_path.get_managed_code_dir()

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
                    deps.add(normalize_interface(action.request_body.model.__name__))
                if action.response_body:
                    deps.add(normalize_interface(action.response_body.model.__name__))

            # Generate imports
            imports = [
                "import { __request, FetchErrorBase } from '../api';",
                f"import type {{ {', '.join(deps)} }} from './models';",
            ]

            (controller_dir / "actions.ts").write_text(
                "\n\n".join(imports + actions_ts)
            )

    def _generate_link_shortcuts(self):
        """Generate TypeScript link formatters for each controller"""
        for controller_id, parsed_controller in self.parsed_controllers.items():
            if parsed_controller.is_layout:
                continue

            controller_dir = parsed_controller.view_path.get_managed_code_dir()

            # Generate link content
            link_content = self.link_converter.convert_controller_links(
                parsed_controller.wrapper, parsed_controller.url_prefix or ""
            )

            if link_content:
                content = ["import { __getLink } from '../api';", "", link_content]
                (controller_dir / "links.ts").write_text("\n".join(content))
            else:
                (controller_dir / "links.ts").write_text("")

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
            local_name = f"{controller_id}GetLinks"
            imports.append(f"import {{ getLink as {local_name} }} from '{rel_import}';")
            link_setters[controller_id] = local_name

        content = [
            *imports,
            "",
            f"const linkGenerator = {link_setters};",
            "",
            "export default linkGenerator;",
        ]

        (global_dir / "links.ts").write_text("\n".join(content))

    def _generate_view_servers(self):
        """Generate useServer hooks for each controller"""
        for controller_id, parsed_controller in self.parsed_controllers.items():
            if not parsed_controller.wrapper.render:
                continue

            controller_dir = parsed_controller.view_path.get_managed_code_dir()
            # render_model = parsed_controller.wrapper.render.model.__name__

            script = self.hook_converter.convert_controller_hooks(
                parsed_controller.wrapper, controller_id
            )

            # Write the complete file
            (controller_dir / "useServer.ts").write_text(script)

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
