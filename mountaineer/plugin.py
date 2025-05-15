from dataclasses import dataclass, field
from pathlib import Path
from typing import Type, TypeAlias

from mountaineer.client_compiler.base import APIBuilderBase
from mountaineer.controller import ControllerBase
from mountaineer.controller_layout import LayoutControllerBase


@dataclass
class BuildConfig:
    custom_builders: list[APIBuilderBase] = field(default_factory=list)


# Proper type alias definition
CONTROLLER_TYPE: TypeAlias = ControllerBase | LayoutControllerBase


@dataclass
class MountaineerPlugin:
    name: str
    controllers: list[Type[CONTROLLER_TYPE]]

    view_root: Path

    build_config: BuildConfig

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
        for controller_cls in self.controllers:
            if controller_cls not in self._concrete_controllers:
                # Assume these controllers have no init params
                self._concrete_controllers[controller_cls] = controller_cls()

        return list(self._concrete_controllers.values())

    def to_webserver(self):
        """
        Shortcut utility to create a webserver from the plugin to allow
        for easy builds of the output files.

        """
        from mountaineer.app import AppController

        app_controller = AppController(
            view_root=self.view_root,
            custom_builders=self.build_config.custom_builders,
        )
        for controller in self.controllers:
            app_controller.register(controller())
        return app_controller
