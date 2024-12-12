from dataclasses import dataclass
from pathlib import Path
from shutil import rmtree as shutil_rmtree
from time import monotonic_ns
from typing import Dict

from inflection import camelize

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
)
from mountaineer.console import CONSOLE
from mountaineer.controller_layout import LayoutControllerBase as LayoutControllerBase
from mountaineer.paths import ManagedViewPath
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

    def _generate_static_files(self):
        """Copy over static files required for the client"""
        managed_code_dir = self.view_root.get_managed_code_dir()
        for static_file in ["api.ts", "live_reload.ts"]:
            content = get_static_path(static_file).read_text()
            (managed_code_dir / static_file).write_text(content)

    def _typescript_prefix_from_module(self, module: str):
        module_parts = module.split(".")
        return "".join([camelize(component) for component in module_parts])
