from dataclasses import dataclass

from mountaineer.client_builder.interface_builders.base import InterfaceBase
from mountaineer.client_builder.parser import (
    ControllerWrapper,
)


@dataclass
class ControllerInterface(InterfaceBase):
    def from_controller(self, controller: ControllerWrapper):
        pass
