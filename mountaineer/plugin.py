from dataclasses import dataclass, field
from pathlib import Path
from typing import Type

from mountaineer.client_compiler.base import APIBuilderBase
from mountaineer.controller import ControllerBase
from mountaineer.controller_layout import LayoutControllerBase


@dataclass
class BuildConfig:
    view_root: Path
    custom_builders: list[APIBuilderBase] = field(default_factory=list)


@dataclass
class MountaineerPlugin:
    name: str
    controllers: list[Type[ControllerBase] | Type[LayoutControllerBase]]

    ssr_root: Path
    static_root: Path

    build_config: BuildConfig

    def to_webserver(self):
        """
        Shortcut utility to create a webserver from the plugin to allow
        for easy builds of the output files.

        """
        from mountaineer.app import AppController

        app_controller = AppController(
            view_root=self.build_config.view_root,
            custom_builders=self.build_config.custom_builders,
        )
        for controller in self.controllers:
            app_controller.register(controller())
        return app_controller
