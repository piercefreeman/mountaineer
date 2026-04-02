from dataclasses import dataclass, field
from pathlib import Path
from typing import Type, TypeAlias

from fastapi import APIRouter

from mountaineer.client_compiler.base import APIBuilderBase
from mountaineer.controller import ControllerBase
from mountaineer.controller_layout import LayoutControllerBase
from mountaineer.paths import ManagedViewPath


@dataclass
class BuildConfig:
    custom_builders: list[APIBuilderBase] = field(default_factory=list)


# Proper type alias definition
CONTROLLER_TYPE: TypeAlias = ControllerBase | LayoutControllerBase


@dataclass
class MountaineerPlugin:
    name: str
    controllers: list[Type[CONTROLLER_TYPE]] | None = None
    view_root: Path | None = None
    build_config: BuildConfig | None = None
    router: APIRouter | None = None

    _concrete_controllers: dict[Type[CONTROLLER_TYPE], CONTROLLER_TYPE] = field(
        default_factory=dict
    )

    def init_controller(self, controller: CONTROLLER_TYPE):
        """
        User-override if they need to specifically initialize a controller with
        custom logic.

        """
        if type(controller) in self._concrete_controllers:
            raise ValueError(f"Controller {type(controller)} already initialized")

        self._concrete_controllers[type(controller)] = controller

    def get_controllers(self):
        """
        All clients that use this plugin should call this function to get the
        concrete controllers.

        """
        # Initialize if not already initialized
        for controller_cls in self.controllers or []:
            if controller_cls not in self._concrete_controllers:
                # Assume these controllers have no init params
                self._concrete_controllers[controller_cls] = controller_cls()

        return list(self._concrete_controllers.values())

    def get_view_root(self) -> Path | None:
        """
        Resolve the plugin view root from explicit configuration or controller
        declarations.

        """
        if self.view_root is not None:
            return self.view_root

        resolved_view_roots = {
            controller.view_path.get_root_link()
            for controller in [
                *(self.controllers or []),
                *self._concrete_controllers.values(),
            ]
            if isinstance(controller.view_path, ManagedViewPath)
        }

        if not resolved_view_roots:
            return None
        if len(resolved_view_roots) > 1:
            raise ValueError(
                f"Plugin {self.name} must use a single view_root across all controllers"
            )

        return next(iter(resolved_view_roots))

    def to_webserver(self):
        """
        Shortcut utility to create a webserver from the plugin to allow
        for easy builds of the output files.

        """
        from mountaineer.app import AppController

        view_root = self.get_view_root()
        if view_root is None:
            raise ValueError(
                f"Plugin {self.name} must define view_root to create a standalone webserver"
            )

        app_controller = AppController(
            view_root=view_root,
            custom_builders=(
                self.build_config.custom_builders if self.build_config else []
            ),
        )
        for controller in self.get_controllers():
            app_controller.register(controller)
        if self.router is not None:
            app_controller.app.include_router(self.router)
        return app_controller
