from pathlib import Path

from mountaineer import mountaineer as mountaineer_rs  # type: ignore
from mountaineer.app import AppController
from mountaineer.client_builder.aliases import AliasManager
from mountaineer.client_builder.manifest import (
    ParsedView,
    build_envelope,
)
from mountaineer.client_builder.parser import (
    ControllerParser,
)
from mountaineer.controller_layout import LayoutControllerBase as LayoutControllerBase
from mountaineer.logging import LOGGER
from mountaineer.paths import ManagedViewPath


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
        for view_root in self._get_all_root_views(build_enabled_only=True):
            view_root.clear_managed_artifact_dirs()

        await self.build_use_server()
        # await self.build_fe_diff(None)

    async def build_use_server(self):
        # Parse all controllers first
        parser, parsed_views = self._parse_all_controllers()
        self._assign_unique_names(parser)
        envelope = build_envelope(
            parser,
            parsed_views,
            self.view_root.get_managed_code_dir(),
        )
        mountaineer_rs.build_client(
            envelope.model_dump_json(
                by_alias=True,
                exclude_defaults=True,
                exclude_none=True,
            )
        )

    def _parse_all_controllers(self):
        """Parse all controllers and store their parsed representations"""
        parser = ControllerParser()
        parsed_controllers: list[ParsedView] = []

        for controller_def in self.app.graph.controllers:
            if controller_def.route is None:
                LOGGER.warning(
                    f"Controller {controller_def.controller.__class__.__name__} has no route"
                )
                continue

            controller = controller_def.controller

            # Parse the controller
            parsed_wrapper = parser.parse_controller(controller.__class__)

            parsed_controllers.append(
                ParsedView(
                    wrapper=parsed_wrapper,
                    view_path=controller_def.view_path,
                    is_layout=isinstance(controller, LayoutControllerBase),
                )
            )

        return parser, parsed_controllers

    def _get_all_root_views(
        self, *, build_enabled_only: bool = False
    ) -> list[ManagedViewPath]:
        view_roots = {self.view_root.copy()}
        for controller_definition in self.app.graph.controllers:
            if build_enabled_only and not controller_definition.build_enabled:
                continue
            view_roots.add(controller_definition.view_root.copy())

        for view_root in view_roots:
            view_root.package_root_link = self.view_root.package_root_link

        return list(view_roots)

    def _assign_unique_names(self, parser: ControllerParser):
        self.alias_manager.assign_global_names(parser)
        self.alias_manager.assign_local_names(parser)
