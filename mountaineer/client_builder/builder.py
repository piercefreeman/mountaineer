from pathlib import Path
from shutil import rmtree as shutil_rmtree
from time import monotonic_ns

from mountaineer.app import AppController
from mountaineer.client_builder.aliases import AliasManager
from mountaineer.client_builder.file_generators.base import ParsedController
from mountaineer.client_builder.file_generators.globals import (
    GlobalControllerGenerator,
    GlobalLinkGenerator,
)
from mountaineer.client_builder.file_generators.locals import (
    LocalActionGenerator,
    LocalIndexGenerator,
    LocalLinkGenerator,
    LocalModelGenerator,
    LocalUseServerGenerator,
)
from mountaineer.client_builder.parser import (
    ControllerParser,
)
from mountaineer.console import CONSOLE
from mountaineer.controller_layout import LayoutControllerBase as LayoutControllerBase
from mountaineer.paths import ManagedViewPath
from mountaineer.static import get_static_path


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

        self.alias_manager = AliasManager()

        self.update_controller(app)

    def update_controller(self, controller: AppController):
        self.app = controller
        self.view_root = ManagedViewPath.from_view_root(controller._view_root)

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
            parser, parsed_controller = self._parse_all_controllers()
            self._assign_unique_names(parser)

            # Generate all the required files
            self._generate_static_files()
            self._generate_global_files(parsed_controller)
            self._generate_local_files(parsed_controller)

        CONSOLE.print(
            f"[bold green]🔨 Built useServer in {(monotonic_ns() - start) / 1e9:.2f}s"
        )

    def _parse_all_controllers(self):
        """Parse all controllers and store their parsed representations"""
        parser = ControllerParser()
        parsed_controllers: list[ParsedController] = []

        for controller_def in self.app.controllers:
            controller = controller_def.controller

            # Parse the controller
            parsed_wrapper = parser.parse_controller(controller.__class__)

            # Get view path
            view_path = self.view_root.get_controller_view_path(controller)

            # Create ParsedController instance
            parsed_controllers.append(
                ParsedController(
                    wrapper=parsed_wrapper,
                    view_path=view_path,
                    url_prefix=controller_def.url_prefix,
                    is_layout=isinstance(controller, LayoutControllerBase),
                )
            )

        return parser, parsed_controllers

    def _assign_unique_names(self, parser: ControllerParser):
        self.alias_manager.assign_global_names(parser)
        self.alias_manager.assign_local_names(parser)

    def _generate_global_files(self, parsed_controllers: list[ParsedController]):
        global_root = self.view_root.get_managed_code_dir()

        global_controller_generator = GlobalControllerGenerator(
            controller_wrappers=[
                controller.wrapper for controller in parsed_controllers
            ],
            managed_path=global_root / "controllers.ts",
        )
        global_link_generator = GlobalLinkGenerator(
            parsed_controllers=parsed_controllers,
            managed_path=global_root / "links.ts",
        )

        global_controller_generator.build()
        global_link_generator.build()

    def _generate_local_files(self, parsed_controllers: list[ParsedController]):
        global_root = self.view_root.get_managed_code_dir()

        for parsed_controller in parsed_controllers:
            managed_path = parsed_controller.view_path.get_managed_code_dir()

            local_link_generator = LocalLinkGenerator(
                controller=parsed_controller.wrapper,
                managed_path=managed_path / "links.ts",
                global_root=global_root,
            )
            local_action_generator = LocalActionGenerator(
                controller=parsed_controller.wrapper,
                managed_path=managed_path / "actions.ts",
                global_root=global_root,
            )
            local_model_generator = LocalModelGenerator(
                controller=parsed_controller.wrapper,
                managed_path=managed_path / "models.ts",
                global_root=global_root,
            )
            local_use_server_generator = LocalUseServerGenerator(
                controller=parsed_controller.wrapper,
                managed_path=managed_path / "useServer.ts",
                global_root=global_root,
            )
            local_index_generator = LocalIndexGenerator(
                controller=parsed_controller.wrapper,
                managed_path=managed_path / "index.ts",
                global_root=global_root,
            )

            # Controller-only Files
            if not parsed_controller.is_layout:
                local_link_generator.build()

            # Controllers + Layout files
            local_action_generator.build()
            local_model_generator.build()
            local_use_server_generator.build()

            # Since the local index generator reads created files on disk to
            # determine what to re-export, it needs to always go after the
            # other generators
            local_index_generator.build()

    def _generate_static_files(self):
        """Copy over static files required for the client"""
        managed_code_dir = self.view_root.get_managed_code_dir()
        for static_file in ["api.ts", "live_reload.ts"]:
            content = get_static_path(static_file).read_text()
            (managed_code_dir / static_file).write_text(content)
